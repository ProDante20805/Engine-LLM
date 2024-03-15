"""
For emitting external monitoring metrics to some sort of store e.g. datadog
Currently distinct from something emitting to a Metrics Store

Used to calculate proportion of successful/unsuccessful requests, differentiates between
docker build vs other errors.

(Copy of model_engine_server/domain/gateways/monitoring_metrics_gateway.py but used purely for
inference to avoid importing stuff in user code that we don't need.)
"""

from abc import ABC, abstractmethod


class InferenceMonitoringMetricsGateway(ABC):
    @abstractmethod
    def emit_attempted_post_inference_hook(self, hook: str):
        """
        Post inference hook succeeded metric

        Args:
            hook: The name of the hook
        """

    @abstractmethod
    def emit_successful_post_inference_hook(self, hook: str):
        """
        Post inference hook succeeded metric

        Args:
            hook: The name of the hook
        """

    @abstractmethod
    def emit_async_task_received_metric(self, queue_name: str):
        """
        Async task received metric

        Args:
            queue_name: The name of the Celery queue
        """
        pass

    @abstractmethod
    def emit_async_task_stuck_metric(self, queue_name: str):
        """
        Async task stuck metric

        Args:
            queue_name: The name of the Celery queue
        """
        pass
