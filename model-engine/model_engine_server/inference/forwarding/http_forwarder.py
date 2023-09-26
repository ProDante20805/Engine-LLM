import argparse
import json
import os
import subprocess
from functools import lru_cache
from multiprocessing import BoundedSemaphore
from multiprocessing.synchronize import BoundedSemaphore as BoundedSemaphoreType
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from model_engine_server.common.dtos.tasks import EndpointPredictV1Request
from model_engine_server.core.loggers import logger_name, make_logger
from model_engine_server.inference.forwarding.forwarding import (
    LoadForwarder,
    LoadStreamingForwarder,
    load_named_config,
)
from sse_starlette.sse import EventSourceResponse

logger = make_logger(logger_name())
app = FastAPI()


class MultiprocessingConcurrencyLimiter:
    def __init__(self, concurrency: Optional[int], fail_on_concurrency_limit: bool):
        if concurrency is not None:
            if concurrency < 1:
                raise ValueError("Concurrency should be at least 1")
            self.semaphore: Optional[BoundedSemaphoreType] = BoundedSemaphore(value=concurrency)
            self.blocking = (
                not fail_on_concurrency_limit
            )  # we want to block if we want to queue up requests
        else:
            self.semaphore = None
            self.blocking = False  # Unused

    def __enter__(self):
        logger.debug("Entering concurrency limiter semaphore")
        if self.semaphore and not self.semaphore.acquire(block=self.blocking):
            logger.warning("Too many requests, returning 429")
            raise HTTPException(status_code=429, detail="Too many requests")
            # Just raises an HTTPException.
            # __exit__ should not run; otherwise the release() doesn't have an acquire()

    def __exit__(self, type, value, traceback):
        logger.debug("Exiting concurrency limiter semaphore")
        if self.semaphore:
            self.semaphore.release()


@app.get("/healthz")
@app.get("/readyz")
def healthcheck():
    return "OK"


def get_config():
    overrides = os.getenv("CONFIG_OVERRIDES")
    config_overrides = None
    if overrides is not None:
        config_overrides = overrides.split(";")
    return load_named_config(
        os.getenv("CONFIG_FILE"),
        config_overrides,
    )


def get_forwarder_loader():
    config = get_config()
    forwarder_loader = LoadForwarder(**config["sync"])
    return forwarder_loader


def get_streaming_forwarder_loader():
    config = get_config()
    streaming_forwarder_loader = LoadStreamingForwarder(**config["stream"])
    return streaming_forwarder_loader


@lru_cache()
def get_concurrency_limiter():
    config = get_config()
    concurrency = int(config.get("max_concurrency", 5))
    return MultiprocessingConcurrencyLimiter(
        concurrency=concurrency, fail_on_concurrency_limit=True
    )


@lru_cache()
def load_forwarder():
    return get_forwarder_loader().load(None, None)


@lru_cache()
def load_streaming_forwarder():
    return get_streaming_forwarder_loader().load(None, None)


@app.post("/predict")
def predict(
    request: EndpointPredictV1Request,
    forwarder=Depends(load_forwarder),
    limiter=Depends(get_concurrency_limiter),
):
    with limiter:
        return forwarder(request.dict())


@app.post("/stream")
async def stream(
    request: EndpointPredictV1Request,
    forwarder=Depends(load_streaming_forwarder),
    limiter=Depends(get_concurrency_limiter),
):
    with limiter:
        try:
            payload = request.dict()
        except Exception:
            logger.error(f"Failed to decode payload from: {request}")
            raise
        else:
            logger.debug(f"Received request: {payload}")

        # has internal error logging for each processing stage
        responses = forwarder(payload)

        async def event_generator():
            for response in responses:
                yield {"data": json.dumps(response)}

        return EventSourceResponse(event_generator())


def entrypoint():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument("--num-workers", type=int, required=True)
    parser.add_argument("--host", type=str, default="[::]")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--set", type=str, action="append")
    parser.add_argument("--graceful-timeout", type=int, default=600)

    args, extra_args = parser.parse_known_args()

    values = [f"CONFIG_FILE={args.config}"]
    if args.set is not None:
        values.append(f"CONFIG_OVERRIDES={';'.join(args.set)}")
    envs = []
    for v in values:
        envs.extend(["--env", v])

    command = [
        "gunicorn",
        "--bind",
        f"{args.host}:{args.port}",
        "--timeout",
        "1200",
        "--keep-alive",
        "2",
        "--worker-class",
        "uvicorn.workers.UvicornWorker",
        "--workers",
        str(args.num_workers),
        "--graceful-timeout",
        str(args.graceful_timeout),
        *envs,
        "model_engine_server.inference.forwarding.http_forwarder:app",
        *extra_args,
    ]
    subprocess.run(command)


if __name__ == "__main__":
    entrypoint()
