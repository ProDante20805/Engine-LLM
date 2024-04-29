"""
TODO figure out how to do: (or if we want to do it)
List model endpoint history: GET model-endpoints/<endpoint id>/history
Read model endpoint creation logs: GET model-endpoints/<endpoint id>/creation-logs
"""

import datetime
import json
import math
import os
import re
from dataclasses import asdict
from typing import Any, AsyncIterable, Dict, List, Optional, Union

from model_engine_server.common.config import hmi_config
from model_engine_server.common.dtos.batch_jobs import CreateDockerImageBatchJobResourceRequests
from model_engine_server.common.dtos.llms import (
    CompletionOutput,
    CompletionStreamOutput,
    CompletionStreamV1Request,
    CompletionStreamV1Response,
    CompletionSyncV1Request,
    CompletionSyncV1Response,
    CreateBatchCompletionsRequest,
    CreateBatchCompletionsResponse,
    CreateLLMModelEndpointV1Request,
    CreateLLMModelEndpointV1Response,
    DeleteLLMEndpointResponse,
    GetLLMModelEndpointV1Response,
    ListLLMModelEndpointsV1Response,
    ModelDownloadRequest,
    ModelDownloadResponse,
    TokenOutput,
    UpdateLLMModelEndpointV1Request,
    UpdateLLMModelEndpointV1Response,
)
from model_engine_server.common.dtos.model_bundles import CreateModelBundleV2Request
from model_engine_server.common.dtos.model_endpoints import ModelEndpointOrderBy
from model_engine_server.common.dtos.tasks import SyncEndpointPredictV1Request, TaskStatus
from model_engine_server.common.resource_limits import validate_resource_requests
from model_engine_server.core.auth.authentication_repository import User
from model_engine_server.core.loggers import (
    LoggerTagKey,
    LoggerTagManager,
    logger_name,
    make_logger,
)
from model_engine_server.domain.entities import (
    GpuType,
    LLMInferenceFramework,
    LLMMetadata,
    LLMSource,
    ModelBundle,
    ModelBundleFlavorType,
    ModelEndpoint,
    ModelEndpointType,
    Quantization,
    RunnableImageFlavor,
    StreamingEnhancedRunnableImageFlavor,
)
from model_engine_server.domain.entities.docker_image_batch_job_bundle_entity import (
    DockerImageBatchJobBundle,
)
from model_engine_server.domain.exceptions import (
    DockerImageNotFoundException,
    EndpointInfraStateNotFound,
    EndpointLabelsException,
    EndpointUnsupportedInferenceTypeException,
    InvalidRequestException,
    ObjectHasInvalidValueException,
    ObjectNotAuthorizedException,
    ObjectNotFoundException,
    UpstreamServiceError,
)
from model_engine_server.domain.gateways import DockerImageBatchJobGateway
from model_engine_server.domain.gateways.llm_artifact_gateway import LLMArtifactGateway
from model_engine_server.domain.repositories import (
    DockerImageBatchJobBundleRepository,
    DockerRepository,
    ModelBundleRepository,
    TokenizerRepository,
)
from model_engine_server.domain.services import LLMModelEndpointService, ModelEndpointService
from model_engine_server.infra.gateways.filesystem_gateway import FilesystemGateway
from model_engine_server.infra.repositories.live_tokenizer_repository import SUPPORTED_MODELS_INFO

from ...common.datadog_utils import add_trace_request_id
from ..authorization.live_authorization_module import LiveAuthorizationModule
from .model_bundle_use_cases import CreateModelBundleV2UseCase
from .model_endpoint_use_cases import (
    CONVERTED_FROM_ARTIFACT_LIKE_KEY,
    _handle_post_inference_hooks,
    model_endpoint_entity_to_get_model_endpoint_response,
    validate_billing_tags,
    validate_deployment_resources,
    validate_labels,
    validate_post_inference_hooks,
)

logger = make_logger(logger_name())


INFERENCE_FRAMEWORK_REPOSITORY: Dict[LLMInferenceFramework, str] = {
    LLMInferenceFramework.DEEPSPEED: "instant-llm",
    LLMInferenceFramework.TEXT_GENERATION_INFERENCE: hmi_config.tgi_repository,
    LLMInferenceFramework.VLLM: hmi_config.vllm_repository,
    LLMInferenceFramework.LIGHTLLM: hmi_config.lightllm_repository,
    LLMInferenceFramework.TENSORRT_LLM: hmi_config.tensorrt_llm_repository,
}

_SUPPORTED_MODELS_BY_FRAMEWORK = {
    LLMInferenceFramework.DEEPSPEED: set(
        [
            "mpt-7b",
            "mpt-7b-instruct",
            "flan-t5-xxl",
            "llama-7b",
            "gpt-j-6b",
            "gpt-j-6b-zh-en",
            "gpt4all-j",
            "dolly-v2-12b",
            "stablelm-tuned-7b",
            "vicuna-13b",
        ]
    ),
    LLMInferenceFramework.TEXT_GENERATION_INFERENCE: set(
        [
            "mpt-7b",
            "mpt-7b-instruct",
            "flan-t5-xxl",
            "llama-7b",
            "llama-2-7b",
            "llama-2-7b-chat",
            "llama-2-13b",
            "llama-2-13b-chat",
            "llama-2-70b",
            "llama-2-70b-chat",
            "falcon-7b",
            "falcon-7b-instruct",
            "falcon-40b",
            "falcon-40b-instruct",
            "codellama-7b",
            "codellama-7b-instruct",
            "codellama-13b",
            "codellama-13b-instruct",
            "codellama-34b",
            "codellama-34b-instruct",
            "llm-jp-13b-instruct-full",
            "llm-jp-13b-instruct-full-dolly",
            "zephyr-7b-alpha",
            "zephyr-7b-beta",
        ]
    ),
    LLMInferenceFramework.VLLM: set(
        [
            "mpt-7b",
            "mpt-7b-instruct",
            "llama-7b",
            "llama-2-7b",
            "llama-2-7b-chat",
            "llama-2-13b",
            "llama-2-13b-chat",
            "llama-2-70b",
            "llama-2-70b-chat",
            "llama-3-8b",
            "llama-3-8b-instruct",
            "llama-3-70b",
            "llama-3-70b-instruct",
            "falcon-7b",
            "falcon-7b-instruct",
            "falcon-40b",
            "falcon-40b-instruct",
            "falcon-180b",
            "falcon-180b-chat",
            "codellama-7b",
            "codellama-7b-instruct",
            "codellama-13b",
            "codellama-13b-instruct",
            "codellama-34b",
            "codellama-34b-instruct",
            "codellama-70b",
            "codellama-70b-instruct",
            "mistral-7b",
            "mistral-7b-instruct",
            "mixtral-8x7b",
            "mixtral-8x7b-instruct",
            "mixtral-8x22b",
            "mixtral-8x22b-instruct",
            "mammoth-coder-llama-2-7b",
            "mammoth-coder-llama-2-13b",
            "mammoth-coder-llama-2-34b",
            "zephyr-7b-alpha",
            "zephyr-7b-beta",
            "gemma-2b",
            "gemma-2b-instruct",
            "gemma-7b",
            "gemma-7b-instruct",
        ]
    ),
    LLMInferenceFramework.LIGHTLLM: set(
        [
            "llama-7b",
            "llama-2-7b",
            "llama-2-7b-chat",
            "llama-2-13b",
            "llama-2-13b-chat",
            "llama-2-70b",
            "llama-2-70b-chat",
        ]
    ),
    LLMInferenceFramework.TENSORRT_LLM: set(["llama-2-7b"]),
}

_SUPPORTED_QUANTIZATIONS: Dict[LLMInferenceFramework, List[Quantization]] = {
    LLMInferenceFramework.DEEPSPEED: [],
    LLMInferenceFramework.TEXT_GENERATION_INFERENCE: [Quantization.BITSANDBYTES],
    LLMInferenceFramework.VLLM: [Quantization.AWQ],
    LLMInferenceFramework.LIGHTLLM: [],
    LLMInferenceFramework.TENSORRT_LLM: [],
}

# We need a dict where if we need to override we can
# NOTE: These are in *descending* order of priority. e.g. if you see 'mammoth-coder'
# you'll use that override and not listen to the 'llama-2' override
_VLLM_MODEL_LENGTH_OVERRIDES: Dict[str, Dict[str, Optional[int]]] = {
    "mammoth-coder": {"max_model_len": 16384, "max_num_batched_tokens": 16384},
    # Based on config here: https://huggingface.co/TIGER-Lab/MAmmoTH-Coder-7B/blob/main/config.json#L12
    # Can also see 13B, 34B there too
    "code-llama": {"max_model_len": 16384, "max_num_batched_tokens": 16384},
    "codellama": {
        "max_model_len": 16384,
        "max_num_batched_tokens": 16384,
    },  # setting both for backwards compatibility, will phase code-llama out in a future pr
    # Based on config here: https://huggingface.co/codellama/CodeLlama-7b-hf/blob/main/config.json#L12
    # Can also see 13B, 34B there too
    "gemma": {"max_model_len": 8192, "max_num_batched_tokens": 8192},
    "llama-2": {"max_model_len": None, "max_num_batched_tokens": 4096},
    "llama-3": {"max_model_len": None, "max_num_batched_tokens": 8192},
    "mistral": {"max_model_len": 8000, "max_num_batched_tokens": 8000},
    "mixtral-8x7b": {"max_model_len": 32768, "max_num_batched_tokens": 32768},
    "mixtral-8x22b": {"max_model_len": 65536, "max_num_batched_tokens": 65536},
    "zephyr": {"max_model_len": 32768, "max_num_batched_tokens": 32768},
}


NUM_DOWNSTREAM_REQUEST_RETRIES = 80  # has to be high enough so that the retries take the 5 minutes
DOWNSTREAM_REQUEST_TIMEOUT_SECONDS = 5 * 60  # 5 minutes


def count_tokens(input: str, model_name: str, tokenizer_repository: TokenizerRepository) -> int:
    """
    Count the number of tokens in the input string.
    """
    tokenizer = tokenizer_repository.load_tokenizer(model_name)
    return len(tokenizer.encode(input))


def _include_safetensors_bin_or_pt(model_files: List[str]) -> Optional[str]:
    """
    This function is used to determine whether to include "*.safetensors", "*.bin", or "*.pt" files
    based on which file type is present most often in the checkpoint folder. The most
    frequently present file type is included.
    In case of ties, priority is given to "*.safetensors", then "*.bin", then "*.pt".
    """
    num_safetensors = len([f for f in model_files if f.endswith(".safetensors")])
    num_bin = len([f for f in model_files if f.endswith(".bin")])
    num_pt = len([f for f in model_files if f.endswith(".pt")])
    maximum = max(num_safetensors, num_bin, num_pt)
    if num_safetensors == maximum:
        return "*.safetensors"
    if num_bin == maximum:
        return "*.bin"
    return "*.pt"


def _model_endpoint_entity_to_get_llm_model_endpoint_response(
    model_endpoint: ModelEndpoint,
) -> GetLLMModelEndpointV1Response:
    if model_endpoint.record.metadata is None or "_llm" not in model_endpoint.record.metadata:
        raise ObjectHasInvalidValueException(
            f"Can't translate model entity to response, endpoint {model_endpoint.record.id} does not have LLM metadata."
        )
    llm_metadata = model_endpoint.record.metadata.get("_llm", {})
    response = GetLLMModelEndpointV1Response(
        id=model_endpoint.record.id,
        name=model_endpoint.record.name,
        model_name=llm_metadata["model_name"],
        source=llm_metadata["source"],
        status=model_endpoint.record.status,
        inference_framework=llm_metadata["inference_framework"],
        inference_framework_image_tag=llm_metadata["inference_framework_image_tag"],
        num_shards=llm_metadata["num_shards"],
        quantize=llm_metadata.get("quantize"),
        checkpoint_path=llm_metadata.get("checkpoint_path"),
        spec=model_endpoint_entity_to_get_model_endpoint_response(model_endpoint),
    )
    return response


def validate_model_name(model_name: str, inference_framework: LLMInferenceFramework) -> None:
    if model_name not in _SUPPORTED_MODELS_BY_FRAMEWORK[inference_framework]:
        raise ObjectHasInvalidValueException(
            f"Model name {model_name} is not supported for inference framework {inference_framework}."
        )


def validate_num_shards(
    num_shards: int, inference_framework: LLMInferenceFramework, gpus: int
) -> None:
    if inference_framework == LLMInferenceFramework.DEEPSPEED:
        if num_shards <= 1:
            raise ObjectHasInvalidValueException("DeepSpeed requires more than 1 GPU.")
        if num_shards != gpus:
            raise ObjectHasInvalidValueException(
                f"Num shard {num_shards} must be the same as number of GPUs {gpus} for DeepSpeed."
            )
    if num_shards > gpus:
        raise ObjectHasInvalidValueException(
            f"Num shard {num_shards} must be less than or equal to the number of GPUs {gpus}."
        )


def validate_quantization(
    quantize: Optional[Quantization], inference_framework: LLMInferenceFramework
) -> None:
    if quantize is not None and quantize not in _SUPPORTED_QUANTIZATIONS[inference_framework]:
        raise ObjectHasInvalidValueException(
            f"Quantization {quantize} is not supported for inference framework {inference_framework}. Supported quantization types are {_SUPPORTED_QUANTIZATIONS[inference_framework]}."
        )


def validate_checkpoint_path_uri(checkpoint_path: str) -> None:
    if not checkpoint_path.startswith("s3://"):
        raise ObjectHasInvalidValueException(
            f"Only S3 paths are supported. Given checkpoint path: {checkpoint_path}."
        )


def get_checkpoint_path(model_name: str, checkpoint_path_override: Optional[str]) -> str:
    checkpoint_path = (
        SUPPORTED_MODELS_INFO[model_name].s3_repo
        if not checkpoint_path_override
        else checkpoint_path_override
    )

    if not checkpoint_path:
        raise InvalidRequestException(f"No checkpoint path found for model {model_name}")

    validate_checkpoint_path_uri(checkpoint_path)
    return checkpoint_path


class CreateLLMModelBundleV1UseCase:
    def __init__(
        self,
        create_model_bundle_use_case: CreateModelBundleV2UseCase,
        model_bundle_repository: ModelBundleRepository,
        llm_artifact_gateway: LLMArtifactGateway,
        docker_repository: DockerRepository,
    ):
        self.authz_module = LiveAuthorizationModule()
        self.create_model_bundle_use_case = create_model_bundle_use_case
        self.model_bundle_repository = model_bundle_repository
        self.llm_artifact_gateway = llm_artifact_gateway
        self.docker_repository = docker_repository

    def check_docker_image_exists_for_image_tag(
        self, framework_image_tag: str, repository_name: str
    ):
        if not self.docker_repository.image_exists(
            image_tag=framework_image_tag,
            repository_name=repository_name,
        ):
            raise DockerImageNotFoundException(
                repository=repository_name,
                tag=framework_image_tag,
            )

    async def execute(
        self,
        user: User,
        endpoint_name: str,
        model_name: str,
        source: LLMSource,
        framework: LLMInferenceFramework,
        framework_image_tag: str,
        endpoint_type: ModelEndpointType,
        num_shards: int,
        quantize: Optional[Quantization],
        checkpoint_path: Optional[str],
    ) -> ModelBundle:
        if source == LLMSource.HUGGING_FACE:
            self.check_docker_image_exists_for_image_tag(
                framework_image_tag, INFERENCE_FRAMEWORK_REPOSITORY[framework]
            )
            if framework == LLMInferenceFramework.DEEPSPEED:
                bundle_id = await self.create_deepspeed_bundle(
                    user,
                    model_name,
                    framework_image_tag,
                    endpoint_type,
                    endpoint_name,
                )
            elif framework == LLMInferenceFramework.TEXT_GENERATION_INFERENCE:
                bundle_id = await self.create_text_generation_inference_bundle(
                    user,
                    model_name,
                    framework_image_tag,
                    endpoint_name,
                    num_shards,
                    quantize,
                    checkpoint_path,
                )
            elif framework == LLMInferenceFramework.VLLM:
                bundle_id = await self.create_vllm_bundle(
                    user,
                    model_name,
                    framework_image_tag,
                    endpoint_name,
                    num_shards,
                    quantize,
                    checkpoint_path,
                )
            elif framework == LLMInferenceFramework.LIGHTLLM:
                bundle_id = await self.create_lightllm_bundle(
                    user,
                    model_name,
                    framework_image_tag,
                    endpoint_name,
                    num_shards,
                    checkpoint_path,
                )
            elif framework == LLMInferenceFramework.TENSORRT_LLM:
                bundle_id = await self.create_tensorrt_llm_bundle(
                    user,
                    framework_image_tag,
                    endpoint_name,
                    num_shards,
                    checkpoint_path,
                )
            else:
                raise ObjectHasInvalidValueException(
                    f"Framework {framework} is not supported for source {source}."
                )
        else:
            raise ObjectHasInvalidValueException(f"Source {source} is not supported.")

        model_bundle = await self.model_bundle_repository.get_model_bundle(bundle_id)
        if model_bundle is None:
            raise ObjectNotFoundException(f"Model bundle {bundle_id} was not found after creation.")
        return model_bundle

    async def create_text_generation_inference_bundle(
        self,
        user: User,
        model_name: str,
        framework_image_tag: str,
        endpoint_unique_name: str,
        num_shards: int,
        quantize: Optional[Quantization],
        checkpoint_path: Optional[str],
    ):
        command = []

        # TGI requires max_input_length < max_total_tokens
        max_input_length = 1024
        max_total_tokens = 2048
        if "llama-2" in model_name:
            max_input_length = 4095
            max_total_tokens = 4096

        subcommands = []

        checkpoint_path = get_checkpoint_path(model_name, checkpoint_path)
        final_weights_folder = "model_files"

        subcommands += self.load_model_weights_sub_commands(
            LLMInferenceFramework.TEXT_GENERATION_INFERENCE,
            framework_image_tag,
            checkpoint_path,
            final_weights_folder,
        )

        subcommands.append(
            f"text-generation-launcher --hostname :: --model-id {final_weights_folder}  --num-shard {num_shards} --port 5005 --max-input-length {max_input_length} --max-total-tokens {max_total_tokens}"
        )

        if quantize:
            subcommands[-1] = subcommands[-1] + f" --quantize {quantize}"
        command = [
            "/bin/bash",
            "-c",
            ";".join(subcommands),
        ]

        return (
            await self.create_model_bundle_use_case.execute(
                user,
                CreateModelBundleV2Request(
                    name=endpoint_unique_name,
                    schema_location="TBA",
                    flavor=StreamingEnhancedRunnableImageFlavor(
                        flavor=ModelBundleFlavorType.STREAMING_ENHANCED_RUNNABLE_IMAGE,
                        repository=hmi_config.tgi_repository,
                        tag=framework_image_tag,
                        command=command,
                        streaming_command=command,
                        protocol="http",
                        readiness_initial_delay_seconds=10,
                        healthcheck_route="/health",
                        predict_route="/generate",
                        streaming_predict_route="/generate_stream",
                        env={},
                    ),
                    metadata={},
                ),
                do_auth_check=False,
                # Skip auth check because llm create endpoint is called as the user itself,
                # but the user isn't directly making the action. It should come from the fine tune
                # job.
            )
        ).model_bundle_id

    def load_model_weights_sub_commands(
        self, framework, framework_image_tag, checkpoint_path, final_weights_folder
    ):
        subcommands = []
        s5cmd = "s5cmd"

        # This is a hack for now to skip installing s5cmd for text-generation-inference:0.9.3-launch_s3,
        # which has s5cmd binary already baked in. Otherwise, install s5cmd if it's not already available
        if (
            framework == LLMInferenceFramework.TEXT_GENERATION_INFERENCE
            and framework_image_tag != "0.9.3-launch_s3"
        ):
            subcommands.append(f"{s5cmd} > /dev/null || conda install -c conda-forge -y {s5cmd}")
        else:
            s5cmd = "./s5cmd"

        base_path = checkpoint_path.split("/")[-1]
        if base_path.endswith(".tar"):
            # If the checkpoint file is a tar file, extract it into final_weights_folder
            subcommands.extend(
                [
                    f"{s5cmd} cp {checkpoint_path} .",
                    f"mkdir -p {final_weights_folder}",
                    f"tar --no-same-owner -xf {base_path} -C {final_weights_folder}",
                ]
            )
        else:
            # Let's check whether to exclude "*.safetensors" or "*.bin" files
            checkpoint_files = self.llm_artifact_gateway.list_files(checkpoint_path)
            model_files = [f for f in checkpoint_files if "model" in f]

            include_str = _include_safetensors_bin_or_pt(model_files)
            file_selection_str = f"--include '*.model' --include '*.json' --include '{include_str}' --exclude 'optimizer*'"
            subcommands.append(
                f"{s5cmd} --numworkers 512 cp --concurrency 10 {file_selection_str} {os.path.join(checkpoint_path, '*')} {final_weights_folder}"
            )

        return subcommands

    def load_model_files_sub_commands_trt_llm(
        self,
        checkpoint_path,
    ):
        """
        This function generate subcommands to load model files for TensorRT-LLM.
        Each model checkpoint is constituted of two folders: `model_weights` which stores the model engine files,
        and `model_tokenizer` which stores the model tokenizer files.
        See llm-engine/model-engine/model_engine_server/inference/tensorrt-llm/triton_model_repo/tensorrt_llm/config.pbtxt
        and llm-engine/model-engine/model_engine_server/inference/tensorrt-llm/triton_model_repo/postprocessing/config.pbtxt
        """
        subcommands = []

        base_path = checkpoint_path.split("/")[-1]

        if base_path.endswith(".tar"):
            raise ObjectHasInvalidValueException(
                "Checkpoint for TensorRT-LLM models must be a folder, not a tar file."
            )
        else:
            subcommands.append(
                f"./s5cmd --numworkers 512 cp --concurrency 50 {os.path.join(checkpoint_path, '*')} ./"
            )

        return subcommands

    async def create_deepspeed_bundle(
        self,
        user: User,
        model_name: str,
        framework_image_tag: str,
        endpoint_type: ModelEndpointType,
        endpoint_unique_name: str,
    ):
        if endpoint_type == ModelEndpointType.STREAMING:
            command = [
                "dumb-init",
                "--",
                "ddtrace-run",
                "run-streamer",
                "--http",
                "production_threads",
                "--concurrency",
                "1",
                "--config",
                "/install/spellbook/inference/service--spellbook_streaming_inference.yaml",
            ]
            return (
                await self.create_model_bundle_use_case.execute(
                    user,
                    CreateModelBundleV2Request(
                        name=endpoint_unique_name,
                        schema_location="TBA",
                        flavor=StreamingEnhancedRunnableImageFlavor(
                            flavor=ModelBundleFlavorType.STREAMING_ENHANCED_RUNNABLE_IMAGE,
                            repository="instant-llm",  # TODO: let user choose repo
                            tag=framework_image_tag,
                            command=command,
                            streaming_command=command,
                            env={
                                "MODEL_NAME": model_name,
                            },
                            protocol="http",
                            readiness_initial_delay_seconds=60,
                        ),
                        metadata={},
                    ),
                    do_auth_check=False,
                )
            ).model_bundle_id
        else:
            return (
                await self.create_model_bundle_use_case.execute(
                    user,
                    CreateModelBundleV2Request(
                        name=endpoint_unique_name,
                        schema_location="TBA",
                        flavor=RunnableImageFlavor(
                            flavor=ModelBundleFlavorType.RUNNABLE_IMAGE,
                            repository="instant-llm",
                            tag=framework_image_tag,
                            command=[
                                "dumb-init",
                                "--",
                                "ddtrace-run",
                                "run-service",
                                "--http",
                                "production_threads",
                                "--concurrency",
                                "1",
                                "--config",
                                "/install/spellbook/inference/service--spellbook_inference.yaml",
                            ],
                            env={
                                "MODEL_NAME": model_name,
                            },
                            protocol="http",
                            readiness_initial_delay_seconds=1800,
                        ),
                        metadata={},
                    ),
                    do_auth_check=False,
                )
            ).model_bundle_id

    async def create_vllm_bundle(
        self,
        user: User,
        model_name: str,
        framework_image_tag: str,
        endpoint_unique_name: str,
        num_shards: int,
        quantize: Optional[Quantization],
        checkpoint_path: Optional[str],
    ):
        command = []

        max_num_batched_tokens: Optional[int] = 2560  # vLLM's default
        max_model_len: Optional[int] = None

        for key, value in _VLLM_MODEL_LENGTH_OVERRIDES.items():
            if key in model_name:
                max_model_len = value["max_model_len"]
                max_num_batched_tokens = value["max_num_batched_tokens"]
                break

        subcommands = []

        checkpoint_path = get_checkpoint_path(model_name, checkpoint_path)
        # added as workaround since transformers doesn't support mistral yet, vllm expects "mistral" in model weights folder
        if "mistral" in model_name:
            final_weights_folder = "mistral_files"
        else:
            final_weights_folder = "model_files"
        subcommands += self.load_model_weights_sub_commands(
            LLMInferenceFramework.VLLM,
            framework_image_tag,
            checkpoint_path,
            final_weights_folder,
        )

        if max_model_len:
            subcommands.append(
                f"python -m vllm_server --model {final_weights_folder} --tensor-parallel-size {num_shards} --port 5005 --max-num-batched-tokens {max_num_batched_tokens} --max-model-len {max_model_len}"
            )
        else:
            subcommands.append(
                f"python -m vllm_server --model {final_weights_folder} --tensor-parallel-size {num_shards} --port 5005 --max-num-batched-tokens {max_num_batched_tokens}"
            )

        if quantize:
            if quantize == Quantization.AWQ:
                subcommands[-1] = subcommands[-1] + f" --quantization {quantize}"
            else:
                raise InvalidRequestException(f"Quantization {quantize} is not supported by vLLM.")

        if hmi_config.sensitive_log_mode:  # pragma: no cover
            subcommands[-1] = subcommands[-1] + " --disable-log-requests"

        command = [
            "/bin/bash",
            "-c",
            ";".join(subcommands),
        ]

        return (
            await self.create_model_bundle_use_case.execute(
                user,
                CreateModelBundleV2Request(
                    name=endpoint_unique_name,
                    schema_location="TBA",
                    flavor=StreamingEnhancedRunnableImageFlavor(
                        flavor=ModelBundleFlavorType.STREAMING_ENHANCED_RUNNABLE_IMAGE,
                        repository=hmi_config.vllm_repository,
                        tag=framework_image_tag,
                        command=command,
                        streaming_command=command,
                        protocol="http",
                        readiness_initial_delay_seconds=10,
                        healthcheck_route="/health",
                        predict_route="/predict",
                        streaming_predict_route="/stream",
                        env={},
                    ),
                    metadata={},
                ),
                do_auth_check=False,
                # Skip auth check because llm create endpoint is called as the user itself,
                # but the user isn't directly making the action. It should come from the fine tune
                # job.
            )
        ).model_bundle_id

    async def create_lightllm_bundle(
        self,
        user: User,
        model_name: str,
        framework_image_tag: str,
        endpoint_unique_name: str,
        num_shards: int,
        checkpoint_path: Optional[str],
    ):
        command = []

        # TODO: incorporate auto calculate max_total_token_num from https://github.com/ModelTC/lightllm/pull/81
        max_total_token_num = 6000  # LightLLM default
        if num_shards == 1:
            max_total_token_num = 15000  # Default for Llama 2 7B on 1 x A10
        elif num_shards == 2:
            max_total_token_num = 21000  # Default for Llama 2 13B on 2 x A10
        elif num_shards == 4:
            max_total_token_num = 70000  # Default for Llama 2 13B on 4 x A10
        max_req_input_len = 2047
        max_req_total_len = 2048
        if "llama-2" in model_name:
            max_req_input_len = 4095
            max_req_total_len = 4096

        subcommands = []

        checkpoint_path = get_checkpoint_path(model_name, checkpoint_path)
        final_weights_folder = "model_files"
        subcommands += self.load_model_weights_sub_commands(
            LLMInferenceFramework.LIGHTLLM,
            framework_image_tag,
            checkpoint_path,
            final_weights_folder,
        )

        subcommands.append(
            f"python -m lightllm.server.api_server --model_dir {final_weights_folder} --port 5005 --tp {num_shards} --max_total_token_num {max_total_token_num} --max_req_input_len {max_req_input_len} --max_req_total_len {max_req_total_len} --tokenizer_mode auto"
        )

        command = [
            "/bin/bash",
            "-c",
            ";".join(subcommands),
        ]

        return (
            await self.create_model_bundle_use_case.execute(
                user,
                CreateModelBundleV2Request(
                    name=endpoint_unique_name,
                    schema_location="TBA",
                    flavor=StreamingEnhancedRunnableImageFlavor(
                        flavor=ModelBundleFlavorType.STREAMING_ENHANCED_RUNNABLE_IMAGE,
                        repository=hmi_config.lightllm_repository,
                        tag=framework_image_tag,
                        command=command,
                        streaming_command=command,
                        protocol="http",
                        readiness_initial_delay_seconds=10,
                        healthcheck_route="/health",
                        predict_route="/generate",
                        streaming_predict_route="/generate_stream",
                        env={},
                    ),
                    metadata={},
                ),
                do_auth_check=False,
                # Skip auth check because llm create endpoint is called as the user itself,
                # but the user isn't directly making the action. It should come from the fine tune
                # job.
            )
        ).model_bundle_id

    async def create_tensorrt_llm_bundle(
        self,
        user: User,
        framework_image_tag: str,
        endpoint_unique_name: str,
        num_shards: int,
        checkpoint_path: Optional[str],
    ):
        command = []

        subcommands = []

        if not checkpoint_path:
            raise ObjectHasInvalidValueException(
                "Checkpoint must be provided for TensorRT-LLM models."
            )

        validate_checkpoint_path_uri(checkpoint_path)

        subcommands += self.load_model_files_sub_commands_trt_llm(
            checkpoint_path,
        )

        subcommands.append(
            f"python3 launch_triton_server.py --world_size={num_shards} --model_repo=./model_repo/"
        )

        command = [
            "/bin/bash",
            "-c",
            ";".join(subcommands),
        ]

        return (
            await self.create_model_bundle_use_case.execute(
                user,
                CreateModelBundleV2Request(
                    name=endpoint_unique_name,
                    schema_location="TBA",
                    flavor=StreamingEnhancedRunnableImageFlavor(
                        flavor=ModelBundleFlavorType.STREAMING_ENHANCED_RUNNABLE_IMAGE,
                        repository=hmi_config.tensorrt_llm_repository,
                        tag=framework_image_tag,
                        command=command,
                        streaming_command=command,
                        protocol="http",
                        readiness_initial_delay_seconds=10,
                        healthcheck_route="/v2/health/ready",
                        # See https://github.com/triton-inference-server/server/blob/main/docs/protocol/extension_generate.md
                        predict_route="/v2/models/ensemble/generate",
                        streaming_predict_route="/v2/models/ensemble/generate_stream",
                        env={},
                    ),
                    metadata={},
                ),
                do_auth_check=False,
                # Skip auth check because llm create endpoint is called as the user itself,
                # but the user isn't directly making the action. It should come from the fine tune
                # job.
            )
        ).model_bundle_id


class CreateLLMModelEndpointV1UseCase:
    def __init__(
        self,
        create_llm_model_bundle_use_case: CreateLLMModelBundleV1UseCase,
        model_endpoint_service: ModelEndpointService,
        docker_repository: DockerRepository,
    ):
        self.authz_module = LiveAuthorizationModule()
        self.create_llm_model_bundle_use_case = create_llm_model_bundle_use_case
        self.model_endpoint_service = model_endpoint_service
        self.docker_repository = docker_repository

    async def execute(
        self, user: User, request: CreateLLMModelEndpointV1Request
    ) -> CreateLLMModelEndpointV1Response:
        validate_deployment_resources(
            min_workers=request.min_workers,
            max_workers=request.max_workers,
            endpoint_type=request.endpoint_type,
        )
        if request.labels is None:
            raise EndpointLabelsException("Endpoint labels cannot be None!")
        validate_labels(request.labels)
        validate_billing_tags(request.billing_tags)
        validate_post_inference_hooks(user, request.post_inference_hooks)
        validate_model_name(request.model_name, request.inference_framework)
        validate_num_shards(request.num_shards, request.inference_framework, request.gpus)
        validate_quantization(request.quantize, request.inference_framework)

        if request.inference_framework in [
            LLMInferenceFramework.TEXT_GENERATION_INFERENCE,
            LLMInferenceFramework.VLLM,
            LLMInferenceFramework.LIGHTLLM,
            LLMInferenceFramework.TENSORRT_LLM,
        ]:
            if request.endpoint_type != ModelEndpointType.STREAMING:
                raise ObjectHasInvalidValueException(
                    f"Creating endpoint type {str(request.endpoint_type)} is not allowed. Can only create streaming endpoints for text-generation-inference, vLLM, LightLLM, and TensorRT-LLM."
                )

        if request.inference_framework_image_tag == "latest":
            request.inference_framework_image_tag = self.docker_repository.get_latest_image_tag(
                INFERENCE_FRAMEWORK_REPOSITORY[request.inference_framework]
            )

        bundle = await self.create_llm_model_bundle_use_case.execute(
            user,
            endpoint_name=request.name,
            model_name=request.model_name,
            source=request.source,
            framework=request.inference_framework,
            framework_image_tag=request.inference_framework_image_tag,
            endpoint_type=request.endpoint_type,
            num_shards=request.num_shards,
            quantize=request.quantize,
            checkpoint_path=request.checkpoint_path,
        )
        validate_resource_requests(
            bundle=bundle,
            cpus=request.cpus,
            memory=request.memory,
            storage=request.storage,
            gpus=request.gpus,
            gpu_type=request.gpu_type,
        )

        prewarm = request.prewarm
        if prewarm is None:
            prewarm = True

        high_priority = request.high_priority
        if high_priority is None:
            high_priority = False

        aws_role = self.authz_module.get_aws_role_for_user(user)
        results_s3_bucket = self.authz_module.get_s3_bucket_for_user(user)

        request.metadata["_llm"] = asdict(
            LLMMetadata(
                model_name=request.model_name,
                source=request.source,
                inference_framework=request.inference_framework,
                inference_framework_image_tag=request.inference_framework_image_tag,
                num_shards=request.num_shards,
                quantize=request.quantize,
                checkpoint_path=request.checkpoint_path,
            )
        )

        model_endpoint_record = await self.model_endpoint_service.create_model_endpoint(
            name=request.name,
            created_by=user.user_id,
            model_bundle_id=bundle.id,
            endpoint_type=request.endpoint_type,
            metadata=request.metadata,
            post_inference_hooks=request.post_inference_hooks,
            child_fn_info=None,
            cpus=request.cpus,
            gpus=request.gpus,
            memory=request.memory,
            gpu_type=request.gpu_type,
            storage=request.storage,
            optimize_costs=bool(request.optimize_costs),
            min_workers=request.min_workers,
            max_workers=request.max_workers,
            per_worker=request.per_worker,
            labels=request.labels,
            aws_role=aws_role,
            results_s3_bucket=results_s3_bucket,
            prewarm=prewarm,
            high_priority=high_priority,
            owner=user.team_id,
            default_callback_url=request.default_callback_url,
            default_callback_auth=request.default_callback_auth,
            public_inference=request.public_inference,
        )
        _handle_post_inference_hooks(
            created_by=user.user_id,
            name=request.name,
            post_inference_hooks=request.post_inference_hooks,
        )

        await self.model_endpoint_service.get_inference_auto_scaling_metrics_gateway().emit_prewarm_metric(
            model_endpoint_record.id
        )

        return CreateLLMModelEndpointV1Response(
            endpoint_creation_task_id=model_endpoint_record.creation_task_id  # type: ignore
        )


class ListLLMModelEndpointsV1UseCase:
    """
    Use case for listing all LLM Model Endpoint of a given user and model endpoint name.
    Also include public_inference LLM endpoints.
    """

    def __init__(self, llm_model_endpoint_service: LLMModelEndpointService):
        self.llm_model_endpoint_service = llm_model_endpoint_service

    async def execute(
        self, user: User, name: Optional[str], order_by: Optional[ModelEndpointOrderBy]
    ) -> ListLLMModelEndpointsV1Response:
        """
        Runs the use case to list all Model Endpoints owned by the user with the given name.

        Args:
            user: The owner of the model endpoint(s).
            name: The name of the Model Endpoint(s).
            order_by: An optional argument to specify the output ordering of the model endpoints.

        Returns:
            A response object that contains the model endpoints.
        """
        model_endpoints = await self.llm_model_endpoint_service.list_llm_model_endpoints(
            owner=user.team_id, name=name, order_by=order_by
        )
        return ListLLMModelEndpointsV1Response(
            model_endpoints=[
                _model_endpoint_entity_to_get_llm_model_endpoint_response(m)
                for m in model_endpoints
            ]
        )


class GetLLMModelEndpointByNameV1UseCase:
    """
    Use case for getting an LLM Model Endpoint of a given user by name.
    """

    def __init__(self, llm_model_endpoint_service: LLMModelEndpointService):
        self.llm_model_endpoint_service = llm_model_endpoint_service
        self.authz_module = LiveAuthorizationModule()

    async def execute(self, user: User, model_endpoint_name: str) -> GetLLMModelEndpointV1Response:
        """
        Runs the use case to get the LLM endpoint with the given name.

        Args:
            user: The owner of the model endpoint.
            model_endpoint_name: The name of the model endpoint.

        Returns:
            A response object that contains the model endpoint.

        Raises:
            ObjectNotFoundException: If a model endpoint with the given name could not be found.
            ObjectNotAuthorizedException: If the owner does not own the model endpoint.
        """
        model_endpoint = await self.llm_model_endpoint_service.get_llm_model_endpoint(
            model_endpoint_name
        )
        if not model_endpoint:
            raise ObjectNotFoundException
        if not self.authz_module.check_access_read_owned_entity(
            user, model_endpoint.record
        ) and not self.authz_module.check_endpoint_public_inference_for_user(
            user, model_endpoint.record
        ):
            raise ObjectNotAuthorizedException
        return _model_endpoint_entity_to_get_llm_model_endpoint_response(model_endpoint)


class UpdateLLMModelEndpointV1UseCase:
    def __init__(
        self,
        create_llm_model_bundle_use_case: CreateLLMModelBundleV1UseCase,
        model_endpoint_service: ModelEndpointService,
        llm_model_endpoint_service: LLMModelEndpointService,
        docker_repository: DockerRepository,
    ):
        self.authz_module = LiveAuthorizationModule()
        self.create_llm_model_bundle_use_case = create_llm_model_bundle_use_case
        self.model_endpoint_service = model_endpoint_service
        self.llm_model_endpoint_service = llm_model_endpoint_service
        self.docker_repository = docker_repository

    async def execute(
        self, user: User, model_endpoint_name: str, request: UpdateLLMModelEndpointV1Request
    ) -> UpdateLLMModelEndpointV1Response:
        if request.labels is not None:
            validate_labels(request.labels)
        validate_billing_tags(request.billing_tags)
        validate_post_inference_hooks(user, request.post_inference_hooks)

        model_endpoint = await self.llm_model_endpoint_service.get_llm_model_endpoint(
            model_endpoint_name
        )
        if not model_endpoint:
            raise ObjectNotFoundException
        if not self.authz_module.check_access_write_owned_entity(user, model_endpoint.record):
            raise ObjectNotAuthorizedException

        endpoint_record = model_endpoint.record
        model_endpoint_id = endpoint_record.id
        bundle = endpoint_record.current_model_bundle

        # TODO: We may want to consider what happens if an endpoint gets stuck in UPDATE_PENDING
        #  on first creating it, and we need to find a way to get it unstuck. This would end up
        # causing endpoint.infra_state to be None.
        if model_endpoint.infra_state is None:
            error_msg = f"Endpoint infra state not found for {model_endpoint_name=}"
            logger.error(error_msg)
            raise EndpointInfraStateNotFound(error_msg)

        infra_state = model_endpoint.infra_state

        if (
            request.model_name
            or request.source
            or request.inference_framework_image_tag
            or request.num_shards
            or request.quantize
            or request.checkpoint_path
        ):
            llm_metadata = (model_endpoint.record.metadata or {}).get("_llm", {})
            inference_framework = llm_metadata["inference_framework"]

            if request.inference_framework_image_tag == "latest":
                inference_framework_image_tag = self.docker_repository.get_latest_image_tag(
                    INFERENCE_FRAMEWORK_REPOSITORY[inference_framework]
                )
            else:
                inference_framework_image_tag = (
                    request.inference_framework_image_tag
                    or llm_metadata["inference_framework_image_tag"]
                )

            model_name = request.model_name or llm_metadata["model_name"]
            source = request.source or llm_metadata["source"]
            num_shards = request.num_shards or llm_metadata["num_shards"]
            quantize = request.quantize or llm_metadata.get("quantize")
            checkpoint_path = request.checkpoint_path or llm_metadata.get("checkpoint_path")

            validate_model_name(model_name, inference_framework)
            validate_num_shards(
                num_shards, inference_framework, request.gpus or infra_state.resource_state.gpus
            )
            validate_quantization(quantize, inference_framework)

            bundle = await self.create_llm_model_bundle_use_case.execute(
                user,
                endpoint_name=model_endpoint_name,
                model_name=model_name,
                source=source,
                framework=inference_framework,
                framework_image_tag=inference_framework_image_tag,
                endpoint_type=endpoint_record.endpoint_type,
                num_shards=num_shards,
                quantize=quantize,
                checkpoint_path=checkpoint_path,
            )

            metadata = endpoint_record.metadata or {}
            metadata["_llm"] = asdict(
                LLMMetadata(
                    model_name=model_name,
                    source=source,
                    inference_framework=inference_framework,
                    inference_framework_image_tag=inference_framework_image_tag,
                    num_shards=num_shards,
                    quantize=quantize,
                    checkpoint_path=checkpoint_path,
                )
            )
            request.metadata = metadata

        # For resources that are not specified in the update endpoint request, pass in resource from
        # infra_state to make sure that after the update, all resources are valid and in sync.
        # E.g. If user only want to update gpus and leave gpu_type as None, we use the existing gpu_type
        # from infra_state to avoid passing in None to validate_resource_requests.
        validate_resource_requests(
            bundle=bundle,
            cpus=request.cpus or infra_state.resource_state.cpus,
            memory=request.memory or infra_state.resource_state.memory,
            storage=request.storage or infra_state.resource_state.storage,
            gpus=request.gpus or infra_state.resource_state.gpus,
            gpu_type=request.gpu_type or infra_state.resource_state.gpu_type,
        )

        validate_deployment_resources(
            min_workers=request.min_workers,
            max_workers=request.max_workers,
            endpoint_type=endpoint_record.endpoint_type,
        )

        if request.metadata is not None and CONVERTED_FROM_ARTIFACT_LIKE_KEY in request.metadata:
            raise ObjectHasInvalidValueException(
                f"{CONVERTED_FROM_ARTIFACT_LIKE_KEY} is a reserved metadata key and cannot be used by user."
            )

        updated_endpoint_record = await self.model_endpoint_service.update_model_endpoint(
            model_endpoint_id=model_endpoint_id,
            model_bundle_id=bundle.id,
            metadata=request.metadata,
            post_inference_hooks=request.post_inference_hooks,
            cpus=request.cpus,
            gpus=request.gpus,
            memory=request.memory,
            gpu_type=request.gpu_type,
            storage=request.storage,
            optimize_costs=request.optimize_costs,
            min_workers=request.min_workers,
            max_workers=request.max_workers,
            per_worker=request.per_worker,
            labels=request.labels,
            prewarm=request.prewarm,
            high_priority=request.high_priority,
            default_callback_url=request.default_callback_url,
            default_callback_auth=request.default_callback_auth,
            public_inference=request.public_inference,
        )
        _handle_post_inference_hooks(
            created_by=endpoint_record.created_by,
            name=updated_endpoint_record.name,
            post_inference_hooks=request.post_inference_hooks,
        )

        return UpdateLLMModelEndpointV1Response(
            endpoint_creation_task_id=updated_endpoint_record.creation_task_id  # type: ignore
        )


class DeleteLLMEndpointByNameUseCase:
    """
    Use case for deleting an LLM Model Endpoint of a given user by endpoint name.
    """

    def __init__(
        self,
        model_endpoint_service: ModelEndpointService,
        llm_model_endpoint_service: LLMModelEndpointService,
    ):
        self.model_endpoint_service = model_endpoint_service
        self.llm_model_endpoint_service = llm_model_endpoint_service
        self.authz_module = LiveAuthorizationModule()

    async def execute(self, user: User, model_endpoint_name: str) -> DeleteLLMEndpointResponse:
        """
        Runs the use case to delete the LLM endpoint owned by the user with the given name.

        Args:
            user: The owner of the model endpoint.
            model_endpoint_name: The name of the model endpoint.

        Returns:
            A response object that contains a boolean indicating if deletion was successful.

        Raises:
            ObjectNotFoundException: If a model endpoint with the given name could not be found.
            ObjectNotAuthorizedException: If the owner does not own the model endpoint.
        """
        model_endpoints = await self.llm_model_endpoint_service.list_llm_model_endpoints(
            owner=user.user_id, name=model_endpoint_name, order_by=None
        )
        if len(model_endpoints) != 1:
            raise ObjectNotFoundException
        model_endpoint = model_endpoints[0]
        if not self.authz_module.check_access_write_owned_entity(user, model_endpoint.record):
            raise ObjectNotAuthorizedException
        await self.model_endpoint_service.delete_model_endpoint(model_endpoint.record.id)
        return DeleteLLMEndpointResponse(deleted=True)


def deepspeed_result_to_tokens(result: Dict[str, Any]) -> List[TokenOutput]:
    tokens = []
    for i in range(len(result["token_probs"]["token_probs"])):
        tokens.append(
            TokenOutput(
                token=result["token_probs"]["tokens"][i],
                log_prob=math.log(result["token_probs"]["token_probs"][i]),
            )
        )
    return tokens


def validate_and_update_completion_params(
    inference_framework: LLMInferenceFramework,
    request: Union[CompletionSyncV1Request, CompletionStreamV1Request],
) -> Union[CompletionSyncV1Request, CompletionStreamV1Request]:
    # top_k, top_p
    if inference_framework in [
        LLMInferenceFramework.TEXT_GENERATION_INFERENCE,
        LLMInferenceFramework.VLLM,
        LLMInferenceFramework.LIGHTLLM,
    ]:
        if request.temperature == 0:
            if request.top_k not in [-1, None] or request.top_p not in [1.0, None]:
                raise ObjectHasInvalidValueException(
                    "top_k and top_p can't be enabled when temperature is 0."
                )
        if request.top_k == 0:
            raise ObjectHasInvalidValueException(
                "top_k needs to be strictly positive, or set it to be -1 / None to disable top_k."
            )
        if inference_framework == LLMInferenceFramework.TEXT_GENERATION_INFERENCE:
            request.top_k = None if request.top_k == -1 else request.top_k
            request.top_p = None if request.top_p == 1.0 else request.top_p
        if inference_framework in [LLMInferenceFramework.VLLM, LLMInferenceFramework.LIGHTLLM]:
            request.top_k = -1 if request.top_k is None else request.top_k
            request.top_p = 1.0 if request.top_p is None else request.top_p
    else:
        if request.top_k or request.top_p:
            raise ObjectHasInvalidValueException(
                "top_k and top_p are only supported in text-generation-inference, vllm, lightllm."
            )

    # presence_penalty, frequency_penalty
    if inference_framework in [LLMInferenceFramework.VLLM, LLMInferenceFramework.LIGHTLLM]:
        request.presence_penalty = (
            0.0 if request.presence_penalty is None else request.presence_penalty
        )
        request.frequency_penalty = (
            0.0 if request.frequency_penalty is None else request.frequency_penalty
        )
    else:
        if request.presence_penalty or request.frequency_penalty:
            raise ObjectHasInvalidValueException(
                "presence_penalty and frequency_penalty are only supported in vllm, lightllm."
            )

    # return_token_log_probs
    if inference_framework in [
        LLMInferenceFramework.DEEPSPEED,
        LLMInferenceFramework.TEXT_GENERATION_INFERENCE,
        LLMInferenceFramework.VLLM,
        LLMInferenceFramework.LIGHTLLM,
    ]:
        pass
    else:
        if request.return_token_log_probs:
            raise ObjectHasInvalidValueException(
                "return_token_log_probs is only supported in deepspeed, text-generation-inference, vllm, lightllm."
            )

    # include_stop_str_in_output
    if inference_framework == LLMInferenceFramework.VLLM:
        pass
    else:
        if request.include_stop_str_in_output is not None:
            raise ObjectHasInvalidValueException(
                "include_stop_str_in_output is only supported in vllm."
            )

    guided_count = 0
    if request.guided_choice is not None:
        guided_count += 1
    if request.guided_json is not None:
        guided_count += 1
    if request.guided_regex is not None:
        guided_count += 1
    if request.guided_grammar is not None:
        guided_count += 1

    if guided_count > 1:
        raise ObjectHasInvalidValueException(
            "Only one of guided_json, guided_choice, guided_regex, guided_grammar can be enabled."
        )

    if (
        request.guided_choice is not None
        or request.guided_regex is not None
        or request.guided_json is not None
        or request.guided_grammar is not None
    ) and not inference_framework == LLMInferenceFramework.VLLM:
        raise ObjectHasInvalidValueException("Guided decoding is only supported in vllm.")

    return request


class CompletionSyncV1UseCase:
    """
    Use case for running a prompt completion on an LLM endpoint.
    """

    def __init__(
        self,
        model_endpoint_service: ModelEndpointService,
        llm_model_endpoint_service: LLMModelEndpointService,
        tokenizer_repository: TokenizerRepository,
    ):
        self.model_endpoint_service = model_endpoint_service
        self.llm_model_endpoint_service = llm_model_endpoint_service
        self.authz_module = LiveAuthorizationModule()
        self.tokenizer_repository = tokenizer_repository

    def model_output_to_completion_output(
        self,
        model_output: Dict[str, Any],
        model_endpoint: ModelEndpoint,
        prompt: str,
        with_token_probs: Optional[bool],
    ) -> CompletionOutput:
        model_content = _model_endpoint_entity_to_get_llm_model_endpoint_response(model_endpoint)
        if model_content.inference_framework == LLMInferenceFramework.DEEPSPEED:
            completion_token_count = len(model_output["token_probs"]["tokens"])
            tokens = None
            if with_token_probs:
                tokens = deepspeed_result_to_tokens(model_output)
            return CompletionOutput(
                text=model_output["text"],
                num_prompt_tokens=count_tokens(
                    prompt,
                    model_content.model_name,
                    self.tokenizer_repository,
                ),
                num_completion_tokens=completion_token_count,
                tokens=tokens,
            )
        elif model_content.inference_framework == LLMInferenceFramework.TEXT_GENERATION_INFERENCE:
            try:
                tokens = None
                if with_token_probs:
                    tokens = [
                        TokenOutput(token=t["text"], log_prob=t["logprob"])
                        for t in model_output["details"]["tokens"]
                    ]
                return CompletionOutput(
                    text=model_output["generated_text"],
                    num_prompt_tokens=len(model_output["details"]["prefill"]),
                    num_completion_tokens=model_output["details"]["generated_tokens"],
                    tokens=tokens,
                )
            except Exception:
                logger.exception(f"Error parsing text-generation-inference output {model_output}.")
                if model_output.get("error_type") == "validation":
                    raise InvalidRequestException(model_output.get("error"))  # trigger a 400
                else:
                    raise UpstreamServiceError(
                        status_code=500, content=bytes(model_output["error"], "utf-8")
                    )

        elif model_content.inference_framework == LLMInferenceFramework.VLLM:
            tokens = None
            if with_token_probs:
                tokens = [
                    TokenOutput(token=model_output["tokens"][index], log_prob=list(t.values())[0])
                    for index, t in enumerate(model_output["log_probs"])
                ]
            return CompletionOutput(
                text=model_output["text"],
                num_prompt_tokens=model_output["count_prompt_tokens"],
                num_completion_tokens=model_output["count_output_tokens"],
                tokens=tokens,
            )
        elif model_content.inference_framework == LLMInferenceFramework.LIGHTLLM:
            tokens = None
            if with_token_probs:
                tokens = [
                    TokenOutput(token=t["text"], log_prob=t["logprob"])
                    for t in model_output["tokens"]
                ]
            return CompletionOutput(
                text=model_output["generated_text"][0],
                num_prompt_tokens=count_tokens(
                    prompt,
                    model_content.model_name,
                    self.tokenizer_repository,
                ),
                num_completion_tokens=model_output["count_output_tokens"],
                tokens=tokens,
            )
        elif model_content.inference_framework == LLMInferenceFramework.TENSORRT_LLM:
            if not model_content.model_name:
                raise InvalidRequestException(
                    f"Invalid endpoint {model_content.name} has no base model"
                )
            if not prompt:
                raise InvalidRequestException("Prompt must be provided for TensorRT-LLM models.")
            num_prompt_tokens = count_tokens(
                prompt, model_content.model_name, self.tokenizer_repository
            )
            return CompletionOutput(
                # Output is "<s> prompt output"
                text=model_output["text_output"][(len(prompt) + 4) :],
                num_prompt_tokens=num_prompt_tokens,
                num_completion_tokens=len(model_output["token_ids"]) - num_prompt_tokens,
            )
        else:
            raise EndpointUnsupportedInferenceTypeException(
                f"Unsupported inference framework {model_content.inference_framework}"
            )

    async def execute(
        self, user: User, model_endpoint_name: str, request: CompletionSyncV1Request
    ) -> CompletionSyncV1Response:
        """
        Runs the use case to create a sync inference task.

        Args:
            user: The user who is creating the sync inference task.
            model_endpoint_name: The name of the model endpoint for the task.
            request: The body of the request to forward to the endpoint.

        Returns:
            A response object that contains the status and result of the task.

        Raises:
            ObjectNotFoundException: If a model endpoint with the given name could not be found.
            ObjectNotAuthorizedException: If the owner does not own the model endpoint.
        """

        request_id = LoggerTagManager.get(LoggerTagKey.REQUEST_ID)
        add_trace_request_id(request_id)

        model_endpoints = await self.llm_model_endpoint_service.list_llm_model_endpoints(
            owner=user.team_id, name=model_endpoint_name, order_by=None
        )

        if len(model_endpoints) == 0:
            raise ObjectNotFoundException

        if len(model_endpoints) > 1:
            raise ObjectHasInvalidValueException(
                f"Expected 1 LLM model endpoint for model name {model_endpoint_name}, got {len(model_endpoints)}"
            )

        model_endpoint = model_endpoints[0]

        if not self.authz_module.check_access_read_owned_entity(
            user, model_endpoint.record
        ) and not self.authz_module.check_endpoint_public_inference_for_user(
            user, model_endpoint.record
        ):
            raise ObjectNotAuthorizedException

        if (
            model_endpoint.record.endpoint_type is not ModelEndpointType.SYNC
            and model_endpoint.record.endpoint_type is not ModelEndpointType.STREAMING
        ):
            raise EndpointUnsupportedInferenceTypeException(
                f"Endpoint {model_endpoint_name} does not serve sync requests."
            )

        inference_gateway = self.model_endpoint_service.get_sync_model_endpoint_inference_gateway()
        autoscaling_metrics_gateway = (
            self.model_endpoint_service.get_inference_auto_scaling_metrics_gateway()
        )
        await autoscaling_metrics_gateway.emit_inference_autoscaling_metric(
            endpoint_id=model_endpoint.record.id
        )
        endpoint_content = _model_endpoint_entity_to_get_llm_model_endpoint_response(model_endpoint)
        validated_request = validate_and_update_completion_params(
            endpoint_content.inference_framework, request
        )
        if not isinstance(validated_request, CompletionSyncV1Request):
            raise ValueError(
                f"request has type {validated_request.__class__.__name__}, expected type CompletionSyncV1Request"
            )
        request = validated_request

        if endpoint_content.inference_framework == LLMInferenceFramework.DEEPSPEED:
            args: Any = {
                "prompts": [request.prompt],
                "token_probs": True,
                "generate_kwargs": {
                    "do_sample": True,
                    "temperature": request.temperature,
                    "max_new_tokens": request.max_new_tokens,
                },
                "serialize_results_as_string": False,
            }
            if request.stop_sequences is not None:
                # Deepspeed models only accepts one stop sequence
                args["stop_sequence"] = request.stop_sequences[0]

            inference_request = SyncEndpointPredictV1Request(
                args=args,
                num_retries=NUM_DOWNSTREAM_REQUEST_RETRIES,
                timeout_seconds=DOWNSTREAM_REQUEST_TIMEOUT_SECONDS,
            )
            predict_result = await inference_gateway.predict(
                topic=model_endpoint.record.destination, predict_request=inference_request
            )

            if predict_result.status == TaskStatus.SUCCESS and predict_result.result is not None:
                return CompletionSyncV1Response(
                    request_id=request_id,
                    output=self.model_output_to_completion_output(
                        predict_result.result["result"][0],
                        model_endpoint,
                        request.prompt,
                        request.return_token_log_probs,
                    ),
                )
            else:
                raise UpstreamServiceError(
                    status_code=500,
                    content=(
                        predict_result.traceback.encode("utf-8")
                        if predict_result.traceback is not None
                        else b""
                    ),
                )
        elif (
            endpoint_content.inference_framework == LLMInferenceFramework.TEXT_GENERATION_INFERENCE
        ):
            tgi_args: Any = {
                "inputs": request.prompt,
                "parameters": {
                    "max_new_tokens": request.max_new_tokens,
                    "decoder_input_details": True,
                },
            }
            if request.stop_sequences is not None:
                tgi_args["parameters"]["stop"] = request.stop_sequences
            if request.temperature > 0:
                tgi_args["parameters"]["temperature"] = request.temperature
                tgi_args["parameters"]["do_sample"] = True
                tgi_args["parameters"]["top_k"] = request.top_k
                tgi_args["parameters"]["top_p"] = request.top_p
            else:
                tgi_args["parameters"]["do_sample"] = False

            inference_request = SyncEndpointPredictV1Request(
                args=tgi_args,
                num_retries=NUM_DOWNSTREAM_REQUEST_RETRIES,
                timeout_seconds=DOWNSTREAM_REQUEST_TIMEOUT_SECONDS,
            )
            predict_result = await inference_gateway.predict(
                topic=model_endpoint.record.destination, predict_request=inference_request
            )

            if predict_result.status != TaskStatus.SUCCESS or predict_result.result is None:
                raise UpstreamServiceError(
                    status_code=500,
                    content=(
                        predict_result.traceback.encode("utf-8")
                        if predict_result.traceback is not None
                        else b""
                    ),
                )

            output = json.loads(predict_result.result["result"])

            return CompletionSyncV1Response(
                request_id=request_id,
                output=self.model_output_to_completion_output(
                    output, model_endpoint, request.prompt, request.return_token_log_probs
                ),
            )
        elif endpoint_content.inference_framework == LLMInferenceFramework.VLLM:
            vllm_args: Any = {
                "prompt": request.prompt,
                "max_tokens": request.max_new_tokens,
                "presence_penalty": request.presence_penalty,
                "frequency_penalty": request.frequency_penalty,
            }
            if request.stop_sequences is not None:
                vllm_args["stop"] = request.stop_sequences
            vllm_args["temperature"] = request.temperature
            if request.temperature > 0:
                vllm_args["top_k"] = request.top_k
                vllm_args["top_p"] = request.top_p
            if request.return_token_log_probs:
                vllm_args["logprobs"] = 1
            if request.include_stop_str_in_output is not None:
                vllm_args["include_stop_str_in_output"] = request.include_stop_str_in_output
            if request.guided_choice is not None:
                vllm_args["guided_choice"] = request.guided_choice
            if request.guided_regex is not None:
                vllm_args["guided_regex"] = request.guided_regex
            if request.guided_json is not None:
                vllm_args["guided_json"] = request.guided_json
            if request.guided_grammar is not None:
                vllm_args["guided_grammar"] = request.guided_grammar

            inference_request = SyncEndpointPredictV1Request(
                args=vllm_args,
                num_retries=NUM_DOWNSTREAM_REQUEST_RETRIES,
                timeout_seconds=DOWNSTREAM_REQUEST_TIMEOUT_SECONDS,
            )
            predict_result = await inference_gateway.predict(
                topic=model_endpoint.record.destination, predict_request=inference_request
            )

            if predict_result.status != TaskStatus.SUCCESS or predict_result.result is None:
                raise UpstreamServiceError(
                    status_code=500,
                    content=(
                        predict_result.traceback.encode("utf-8")
                        if predict_result.traceback is not None
                        else b""
                    ),
                )

            output = json.loads(predict_result.result["result"])
            return CompletionSyncV1Response(
                request_id=request_id,
                output=self.model_output_to_completion_output(
                    output, model_endpoint, request.prompt, request.return_token_log_probs
                ),
            )
        elif endpoint_content.inference_framework == LLMInferenceFramework.LIGHTLLM:
            lightllm_args: Any = {
                "inputs": request.prompt,
                "parameters": {
                    "max_new_tokens": request.max_new_tokens,
                    "presence_penalty": request.presence_penalty,
                    "frequency_penalty": request.frequency_penalty,
                },
            }
            # TODO: implement stop sequences
            if request.temperature > 0:
                lightllm_args["parameters"]["temperature"] = request.temperature
                lightllm_args["parameters"]["do_sample"] = True
                lightllm_args["top_k"] = request.top_k
                lightllm_args["top_p"] = request.top_p
            else:
                lightllm_args["parameters"]["do_sample"] = False
            if request.return_token_log_probs:
                lightllm_args["parameters"]["return_details"] = True

            inference_request = SyncEndpointPredictV1Request(
                args=lightllm_args,
                num_retries=NUM_DOWNSTREAM_REQUEST_RETRIES,
                timeout_seconds=DOWNSTREAM_REQUEST_TIMEOUT_SECONDS,
            )
            predict_result = await inference_gateway.predict(
                topic=model_endpoint.record.destination, predict_request=inference_request
            )

            if predict_result.status != TaskStatus.SUCCESS or predict_result.result is None:
                raise UpstreamServiceError(
                    status_code=500,
                    content=(
                        predict_result.traceback.encode("utf-8")
                        if predict_result.traceback is not None
                        else b""
                    ),
                )

            output = json.loads(predict_result.result["result"])
            return CompletionSyncV1Response(
                request_id=request_id,
                output=self.model_output_to_completion_output(
                    output, model_endpoint, request.prompt, request.return_token_log_probs
                ),
            )
        elif endpoint_content.inference_framework == LLMInferenceFramework.TENSORRT_LLM:
            # TODO: Stop sequences is buggy and return token logprobs are not supported
            # TODO: verify the implementation of presence_penalty and repetition_penalty
            # and see if they fit our existing definition of presence_penalty and frequency_penalty
            # Ref https://github.com/NVIDIA/FasterTransformer/blob/main/src/fastertransformer/kernels/sampling_penalty_kernels.cu
            trt_llm_args: Any = {
                "text_input": request.prompt,
                "max_tokens": request.max_new_tokens,
                "stop_words": request.stop_sequences if request.stop_sequences else "",
                "bad_words": "",
                "temperature": request.temperature,
            }

            inference_request = SyncEndpointPredictV1Request(
                args=trt_llm_args,
                num_retries=NUM_DOWNSTREAM_REQUEST_RETRIES,
                timeout_seconds=DOWNSTREAM_REQUEST_TIMEOUT_SECONDS,
            )
            predict_result = await inference_gateway.predict(
                topic=model_endpoint.record.destination,
                predict_request=inference_request,
            )

            if predict_result.status != TaskStatus.SUCCESS or predict_result.result is None:
                raise UpstreamServiceError(
                    status_code=500,
                    content=(
                        predict_result.traceback.encode("utf-8")
                        if predict_result.traceback is not None
                        else b""
                    ),
                )

            output = json.loads(predict_result.result["result"])
            return CompletionSyncV1Response(
                request_id=request_id,
                output=self.model_output_to_completion_output(
                    output, model_endpoint, request.prompt, request.return_token_log_probs
                ),
            )
        else:
            raise EndpointUnsupportedInferenceTypeException(
                f"Unsupported inference framework {endpoint_content.inference_framework}"
            )


class CompletionStreamV1UseCase:
    """
    Use case for running a stream prompt completion on an LLM endpoint.
    """

    def __init__(
        self,
        model_endpoint_service: ModelEndpointService,
        llm_model_endpoint_service: LLMModelEndpointService,
        tokenizer_repository: TokenizerRepository,
    ):
        self.model_endpoint_service = model_endpoint_service
        self.llm_model_endpoint_service = llm_model_endpoint_service
        self.authz_module = LiveAuthorizationModule()
        self.tokenizer_repository = tokenizer_repository

    async def execute(
        self, user: User, model_endpoint_name: str, request: CompletionStreamV1Request
    ) -> AsyncIterable[CompletionStreamV1Response]:
        """
        Runs the use case to create a stream inference task.

        Args:
            user: The user who is creating the stream inference task.
            model_endpoint_name: The name of the model endpoint for the task.
            request: The body of the request to forward to the endpoint.

        Returns:
            A response object that contains the status and result of the task.

        Raises:
            ObjectNotFoundException: If a model endpoint with the given name could not be found.
            ObjectNotAuthorizedException: If the owner does not own the model endpoint.
        """

        request_id = LoggerTagManager.get(LoggerTagKey.REQUEST_ID)
        add_trace_request_id(request_id)

        model_endpoints = await self.llm_model_endpoint_service.list_llm_model_endpoints(
            owner=user.team_id, name=model_endpoint_name, order_by=None
        )

        if len(model_endpoints) == 0:
            raise ObjectNotFoundException(f"Model endpoint {model_endpoint_name} not found.")

        if len(model_endpoints) > 1:
            raise ObjectHasInvalidValueException(
                f"Expected 1 LLM model endpoint for model name {model_endpoint_name}, got {len(model_endpoints)}"
            )

        model_endpoint = model_endpoints[0]

        if not self.authz_module.check_access_read_owned_entity(
            user, model_endpoint.record
        ) and not self.authz_module.check_endpoint_public_inference_for_user(
            user, model_endpoint.record
        ):
            raise ObjectNotAuthorizedException

        if model_endpoint.record.endpoint_type != ModelEndpointType.STREAMING:
            raise EndpointUnsupportedInferenceTypeException(
                f"Endpoint {model_endpoint_name} is not a streaming endpoint."
            )

        inference_gateway = (
            self.model_endpoint_service.get_streaming_model_endpoint_inference_gateway()
        )
        autoscaling_metrics_gateway = (
            self.model_endpoint_service.get_inference_auto_scaling_metrics_gateway()
        )
        await autoscaling_metrics_gateway.emit_inference_autoscaling_metric(
            endpoint_id=model_endpoint.record.id
        )

        model_content = _model_endpoint_entity_to_get_llm_model_endpoint_response(model_endpoint)
        validated_request = validate_and_update_completion_params(
            model_content.inference_framework, request
        )
        if not isinstance(validated_request, CompletionStreamV1Request):
            raise ValueError(
                f"request has type {validated_request.__class__.__name__}, expected type CompletionStreamV1Request"
            )
        request = validated_request

        args: Any = None
        num_prompt_tokens = None
        if model_content.inference_framework == LLMInferenceFramework.DEEPSPEED:
            args = {
                "prompts": [request.prompt],
                "token_probs": True,
                "generate_kwargs": {
                    "do_sample": True,
                    "temperature": request.temperature,
                    "max_new_tokens": request.max_new_tokens,
                },
                "serialize_results_as_string": False,
            }
            if request.stop_sequences is not None:
                # Deepspeed models only accepts one stop sequence
                args["stop_sequence"] = request.stop_sequences[0]
            num_prompt_tokens = count_tokens(
                request.prompt,
                model_content.model_name,
                self.tokenizer_repository,
            )
        elif model_content.inference_framework == LLMInferenceFramework.TEXT_GENERATION_INFERENCE:
            args = {
                "inputs": request.prompt,
                "parameters": {
                    "max_new_tokens": request.max_new_tokens,
                },
            }
            if request.stop_sequences is not None:
                args["parameters"]["stop"] = request.stop_sequences
            if request.temperature > 0:
                args["parameters"]["temperature"] = request.temperature
                args["parameters"]["do_sample"] = True
                args["parameters"]["top_k"] = request.top_k
                args["parameters"]["top_p"] = request.top_p
            else:
                args["parameters"]["do_sample"] = False
            num_prompt_tokens = count_tokens(
                request.prompt,
                model_content.model_name,
                self.tokenizer_repository,
            )
        elif model_content.inference_framework == LLMInferenceFramework.VLLM:
            args = {
                "prompt": request.prompt,
                "max_tokens": request.max_new_tokens,
                "presence_penalty": request.presence_penalty,
                "frequency_penalty": request.frequency_penalty,
            }
            if request.stop_sequences is not None:
                args["stop"] = request.stop_sequences
            args["temperature"] = request.temperature
            if request.temperature > 0:
                args["top_k"] = request.top_k
                args["top_p"] = request.top_p
            if request.return_token_log_probs:
                args["logprobs"] = 1
            if request.include_stop_str_in_output is not None:
                args["include_stop_str_in_output"] = request.include_stop_str_in_output
            if request.guided_choice is not None:
                args["guided_choice"] = request.guided_choice
            if request.guided_regex is not None:
                args["guided_regex"] = request.guided_regex
            if request.guided_json is not None:
                args["guided_json"] = request.guided_json
            if request.guided_grammar is not None:
                args["guided_grammar"] = request.guided_grammar
            args["stream"] = True
        elif model_content.inference_framework == LLMInferenceFramework.LIGHTLLM:
            args = {
                "inputs": request.prompt,
                "parameters": {
                    "max_new_tokens": request.max_new_tokens,
                    "presence_penalty": request.presence_penalty,
                    "frequency_penalty": request.frequency_penalty,
                },
            }
            # TODO: stop sequences
            if request.temperature > 0:
                args["parameters"]["temperature"] = request.temperature
                args["parameters"]["do_sample"] = True
                args["parameters"]["top_k"] = request.top_k
                args["parameters"]["top_p"] = request.top_p
            else:
                args["parameters"]["do_sample"] = False
            if request.return_token_log_probs:
                args["parameters"]["return_details"] = True
            num_prompt_tokens = count_tokens(
                request.prompt,
                model_content.model_name,
                self.tokenizer_repository,
            )
        elif model_content.inference_framework == LLMInferenceFramework.TENSORRT_LLM:
            # TODO: Stop sequences is buggy and return token logprobs are not supported
            # TODO: verify the implementation of presence_penalty and repetition_penalty
            # and see if they fit our existing definition of presence_penalty and frequency_penalty
            # Ref https://github.com/NVIDIA/FasterTransformer/blob/main/src/fastertransformer/kernels/sampling_penalty_kernels.cu
            args = {
                "text_input": request.prompt,
                "max_tokens": request.max_new_tokens,
                "stop_words": request.stop_sequences if request.stop_sequences else "",
                "bad_words": "",
                "temperature": request.temperature,
                "stream": True,
            }
            num_prompt_tokens = count_tokens(
                request.prompt,
                model_content.model_name,
                self.tokenizer_repository,
            )

        else:
            raise EndpointUnsupportedInferenceTypeException(
                f"Unsupported inference framework {model_content.inference_framework}"
            )

        inference_request = SyncEndpointPredictV1Request(
            args=args,
            num_retries=NUM_DOWNSTREAM_REQUEST_RETRIES,
            timeout_seconds=DOWNSTREAM_REQUEST_TIMEOUT_SECONDS,
        )
        predict_result = inference_gateway.streaming_predict(
            topic=model_endpoint.record.destination, predict_request=inference_request
        )

        num_completion_tokens = 0
        async for res in predict_result:
            result = res.result
            if model_content.inference_framework == LLMInferenceFramework.DEEPSPEED:
                if res.status == TaskStatus.SUCCESS and result is not None:
                    if "token" in result["result"]:
                        yield CompletionStreamV1Response(
                            request_id=request_id,
                            output=CompletionStreamOutput(
                                text=result["result"]["token"],
                                finished=False,
                                num_prompt_tokens=None,
                                num_completion_tokens=None,
                            ),
                        )
                    else:
                        completion_token_count = len(
                            result["result"]["response"][0]["token_probs"]["tokens"]
                        )
                        yield CompletionStreamV1Response(
                            request_id=request_id,
                            output=CompletionStreamOutput(
                                text=result["result"]["response"][0]["text"],
                                finished=True,
                                num_prompt_tokens=num_prompt_tokens,
                                num_completion_tokens=completion_token_count,
                            ),
                        )
                else:
                    yield CompletionStreamV1Response(
                        request_id=request_id,
                        output=None,
                    )
            elif (
                model_content.inference_framework == LLMInferenceFramework.TEXT_GENERATION_INFERENCE
            ):
                if res.status == TaskStatus.SUCCESS and result is not None:
                    if result["result"].get("generated_text") is not None:
                        finished = True
                    else:
                        finished = False

                    num_completion_tokens += 1

                    token = None
                    if request.return_token_log_probs:
                        token = TokenOutput(
                            token=result["result"]["token"]["text"],
                            log_prob=result["result"]["token"]["logprob"],
                        )
                    try:
                        yield CompletionStreamV1Response(
                            request_id=request_id,
                            output=CompletionStreamOutput(
                                text=result["result"]["token"]["text"],
                                finished=finished,
                                num_prompt_tokens=num_prompt_tokens if finished else None,
                                num_completion_tokens=num_completion_tokens,
                                token=token,
                            ),
                        )
                    except Exception:
                        logger.exception(
                            f"Error parsing text-generation-inference output. Result: {result['result']}"
                        )
                        if result["result"].get("error_type") == "validation":
                            raise InvalidRequestException(
                                result["result"].get("error")
                            )  # trigger a 400
                        else:
                            raise UpstreamServiceError(
                                status_code=500, content=result.get("error")
                            )  # also change llms_v1.py that will return a 500 HTTPException so user can retry

                else:
                    yield CompletionStreamV1Response(
                        request_id=request_id,
                        output=None,
                    )
            elif model_content.inference_framework == LLMInferenceFramework.VLLM:
                if res.status == TaskStatus.SUCCESS and result is not None:
                    token = None
                    if request.return_token_log_probs:
                        token = TokenOutput(
                            token=result["result"]["text"],
                            log_prob=list(result["result"]["log_probs"].values())[0],
                        )
                    finished = result["result"]["finished"]
                    num_prompt_tokens = result["result"]["count_prompt_tokens"]
                    yield CompletionStreamV1Response(
                        request_id=request_id,
                        output=CompletionStreamOutput(
                            text=result["result"]["text"],
                            finished=finished,
                            num_prompt_tokens=num_prompt_tokens if finished else None,
                            num_completion_tokens=result["result"]["count_output_tokens"],
                            token=token,
                        ),
                    )
                else:
                    yield CompletionStreamV1Response(
                        request_id=request_id,
                        output=None,
                    )
            elif model_content.inference_framework == LLMInferenceFramework.LIGHTLLM:
                if res.status == TaskStatus.SUCCESS and result is not None:
                    token = None
                    num_completion_tokens += 1
                    if request.return_token_log_probs:
                        token = TokenOutput(
                            token=result["result"]["token"]["text"],
                            log_prob=result["result"]["token"]["logprob"],
                        )
                    finished = result["result"]["finished"]
                    yield CompletionStreamV1Response(
                        request_id=request_id,
                        output=CompletionStreamOutput(
                            text=result["result"]["token"]["text"],
                            finished=finished,
                            num_prompt_tokens=num_prompt_tokens if finished else None,
                            num_completion_tokens=num_completion_tokens,
                            token=token,
                        ),
                    )
                else:
                    yield CompletionStreamV1Response(
                        request_id=request_id,
                        output=None,
                    )
            elif model_content.inference_framework == LLMInferenceFramework.TENSORRT_LLM:
                if res.status == TaskStatus.SUCCESS and result is not None:
                    num_completion_tokens += 1
                    yield CompletionStreamV1Response(
                        request_id=request_id,
                        output=CompletionStreamOutput(
                            text=result["result"]["text_output"],
                            finished=False,  # Tracked by https://github.com/NVIDIA/TensorRT-LLM/issues/240
                            num_prompt_tokens=num_prompt_tokens,
                            num_completion_tokens=num_completion_tokens,
                        ),
                    )
                else:
                    yield CompletionStreamV1Response(
                        request_id=request_id,
                        output=None,
                    )
            else:
                raise EndpointUnsupportedInferenceTypeException(
                    f"Unsupported inference framework {model_content.inference_framework}"
                )


class ModelDownloadV1UseCase:
    def __init__(
        self,
        filesystem_gateway: FilesystemGateway,
        model_endpoint_service: ModelEndpointService,
        llm_artifact_gateway: LLMArtifactGateway,
    ):
        self.filesystem_gateway = filesystem_gateway
        self.model_endpoint_service = model_endpoint_service
        self.llm_artifact_gateway = llm_artifact_gateway

    async def execute(self, user: User, request: ModelDownloadRequest) -> ModelDownloadResponse:
        model_endpoints = await self.model_endpoint_service.list_model_endpoints(
            owner=user.team_id, name=request.model_name, order_by=None
        )
        if len(model_endpoints) == 0:
            raise ObjectNotFoundException

        if len(model_endpoints) > 1:
            raise ObjectHasInvalidValueException(
                f"Expected 1 LLM model endpoint for model name {request.model_name}, got {len(model_endpoints)}"
            )
        model_files = self.llm_artifact_gateway.get_model_weights_urls(
            user.team_id, request.model_name
        )
        urls = {}
        for model_file in model_files:
            # don't want to make s3 bucket full keys public, so trim to just keep file name
            public_file_name = model_file.rsplit("/", 1)[-1]
            urls[public_file_name] = self.filesystem_gateway.generate_signed_url(model_file)
        return ModelDownloadResponse(urls=urls)


def infer_hardware_from_model_name(model_name: str) -> CreateDockerImageBatchJobResourceRequests:
    if "mixtral-8x7b" in model_name:
        cpus = "20"
        gpus = 2
        memory = "160Gi"
        storage = "160Gi"
        gpu_type = GpuType.NVIDIA_AMPERE_A100E
    elif "mixtral-8x22b" in model_name:
        cpus = "80"
        gpus = 8
        memory = "800Gi"
        storage = "460Gi"
        gpu_type = GpuType.NVIDIA_AMPERE_A100E
    else:
        numbers = re.findall(r"\d+", model_name)
        if len(numbers) == 0:
            raise ObjectHasInvalidValueException(
                f"Model {model_name} is not supported for batch completions."
            )

        b_params = int(numbers[-1])
        if b_params <= 7:
            cpus = "10"
            gpus = 1
            memory = "24Gi"
            storage = "80Gi"
            gpu_type = GpuType.NVIDIA_AMPERE_A10
        elif b_params <= 13:
            cpus = "20"
            gpus = 2
            memory = "48Gi"
            storage = "80Gi"
            gpu_type = GpuType.NVIDIA_AMPERE_A10
        elif b_params <= 34:
            cpus = "40"
            gpus = 4
            memory = "96Gi"
            storage = "96Gi"
            gpu_type = GpuType.NVIDIA_AMPERE_A10
        elif b_params <= 70:
            cpus = "20"
            gpus = 2
            memory = "160Gi"
            storage = "160Gi"
            gpu_type = GpuType.NVIDIA_AMPERE_A100E
        else:
            raise ObjectHasInvalidValueException(
                f"Model {model_name} is not supported for batch completions."
            )

    return CreateDockerImageBatchJobResourceRequests(
        cpus=cpus, gpus=gpus, memory=memory, storage=storage, gpu_type=gpu_type
    )


class CreateBatchCompletionsUseCase:
    def __init__(
        self,
        docker_image_batch_job_gateway: DockerImageBatchJobGateway,
        docker_repository: DockerRepository,
        docker_image_batch_job_bundle_repo: DockerImageBatchJobBundleRepository,
    ):
        self.docker_image_batch_job_gateway = docker_image_batch_job_gateway
        self.docker_repository = docker_repository
        self.docker_image_batch_job_bundle_repo = docker_image_batch_job_bundle_repo

    async def create_batch_job_bundle(
        self,
        user: User,
        request: CreateBatchCompletionsRequest,
        hardware: CreateDockerImageBatchJobResourceRequests,
    ) -> DockerImageBatchJobBundle:
        bundle_name = (
            f"{request.model_config.model}_{datetime.datetime.utcnow().strftime('%y%m%d-%H%M%S')}"
        )

        image_tag = self.docker_repository.get_latest_image_tag(
            hmi_config.batch_inference_vllm_repository
        )

        config_file_path = "/opt/config.json"

        assert hardware.gpu_type is not None

        batch_bundle = (
            await self.docker_image_batch_job_bundle_repo.create_docker_image_batch_job_bundle(
                name=bundle_name,
                created_by=user.user_id,
                owner=user.team_id,
                image_repository=hmi_config.batch_inference_vllm_repository,
                image_tag=image_tag,
                command=[
                    "dumb-init",
                    "--",
                    "/bin/bash",
                    "-c",
                    "ddtrace-run python vllm_batch.py",
                ],
                env={"CONFIG_FILE": config_file_path},
                mount_location=config_file_path,
                cpus=str(hardware.cpus),
                memory=str(hardware.memory),
                storage=str(hardware.storage),
                gpus=hardware.gpus,
                gpu_type=hardware.gpu_type,
                public=False,
            )
        )
        return batch_bundle

    async def execute(
        self, user: User, request: CreateBatchCompletionsRequest
    ) -> CreateBatchCompletionsResponse:
        hardware = infer_hardware_from_model_name(request.model_config.model)
        # Reconcile gpus count with num_shards from request
        assert hardware.gpus is not None
        if request.model_config.num_shards:
            hardware.gpus = max(hardware.gpus, request.model_config.num_shards)
        request.model_config.num_shards = hardware.gpus

        if request.tool_config and request.tool_config.name != "code_evaluator":
            raise ObjectHasInvalidValueException(
                "Only code_evaluator tool is supported for batch completions."
            )

        batch_bundle = await self.create_batch_job_bundle(user, request, hardware)

        validate_resource_requests(
            bundle=batch_bundle,
            cpus=hardware.cpus,
            memory=hardware.memory,
            storage=hardware.storage,
            gpus=hardware.gpus,
            gpu_type=hardware.gpu_type,
        )

        if request.max_runtime_sec is None or request.max_runtime_sec < 1:
            raise ObjectHasInvalidValueException("max_runtime_sec must be a positive integer.")

        job_id = await self.docker_image_batch_job_gateway.create_docker_image_batch_job(
            created_by=user.user_id,
            owner=user.team_id,
            job_config=request.dict(),
            env=batch_bundle.env,
            command=batch_bundle.command,
            repo=batch_bundle.image_repository,
            tag=batch_bundle.image_tag,
            resource_requests=hardware,
            labels=request.model_config.labels,
            mount_location=batch_bundle.mount_location,
            override_job_max_runtime_s=request.max_runtime_sec,
            num_workers=request.data_parallelism,
        )
        return CreateBatchCompletionsResponse(job_id=job_id)
