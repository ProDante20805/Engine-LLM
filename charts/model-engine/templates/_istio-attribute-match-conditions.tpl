{{- /* Generated from the OpenAPI schema with model-engine-internal/scripts/generate_istio_metric_tags.py */}}
{{- define "modelEngine.istioAttributeMatchConditions" -}}
- condition: request.method == 'GET' && request.url_path == '/healthcheck'
  value: get_/healthcheck
- condition: request.method == 'GET' && request.url_path == '/healthz'
  value: get_/healthz
- condition: request.method == 'GET' && request.url_path == '/readyz'
  value: get_/readyz
- condition: request.method == 'POST' && request.url_path == '/v1/async-tasks'
  value: post_/v1/async-tasks
- condition: request.method == 'GET' && request.url_path.matches('^/v1/async-tasks/[[:alnum:]-_]*$')
  value: get_/v1/async-tasks/_task_id
- condition: request.method == 'POST' && request.url_path == '/v1/batch-jobs'
  value: post_/v1/batch-jobs
- condition: request.method == 'GET' && request.url_path.matches('^/v1/batch-jobs/[[:alnum:]-_]*$')
  value: get_/v1/batch-jobs/_batch_job_id
- condition: request.method == 'PUT' && request.url_path.matches('^/v1/batch-jobs/[[:alnum:]-_]*$')
  value: put_/v1/batch-jobs/_batch_job_id
- condition: request.method == 'GET' && request.url_path == '/v1/docker-image-batch-job-bundles'
  value: get_/v1/docker-image-batch-job-bundles
- condition: request.method == 'POST' && request.url_path == '/v1/docker-image-batch-job-bundles'
  value: post_/v1/docker-image-batch-job-bundles
- condition: request.method == 'GET' && request.url_path == '/v1/docker-image-batch-job-bundles/latest'
  value: get_/v1/docker-image-batch-job-bundles/latest
- condition: request.method == 'GET' && request.url_path.matches('^/v1/docker-image-batch-job-bundles/[[:alnum:]-_]*$')
  value: get_/v1/docker-image-batch-job-bundles/_docker_image_batch_job_bundle_id
- condition: request.method == 'GET' && request.url_path == '/v1/docker-image-batch-jobs'
  value: get_/v1/docker-image-batch-jobs
- condition: request.method == 'POST' && request.url_path == '/v1/docker-image-batch-jobs'
  value: post_/v1/docker-image-batch-jobs
- condition: request.method == 'GET' && request.url_path.matches('^/v1/docker-image-batch-jobs/[[:alnum:]-_]*$')
  value: get_/v1/docker-image-batch-jobs/_batch_job_id
- condition: request.method == 'PUT' && request.url_path.matches('^/v1/docker-image-batch-jobs/[[:alnum:]-_]*$')
  value: put_/v1/docker-image-batch-jobs/_batch_job_id
- condition: request.method == 'GET' && request.url_path == '/v1/files'
  value: get_/v1/files
- condition: request.method == 'POST' && request.url_path == '/v1/files'
  value: post_/v1/files
- condition: request.method == 'DELETE' && request.url_path.matches('^/v1/files/[[:alnum:]-_]*$')
  value: delete_/v1/files/_file_id
- condition: request.method == 'GET' && request.url_path.matches('^/v1/files/[[:alnum:]-_]*$')
  value: get_/v1/files/_file_id
- condition: request.method == 'GET' && request.url_path.matches('^/v1/files/[[:alnum:]-_]*/content$')
  value: get_/v1/files/_file_id/content
- condition: request.method == 'POST' && request.url_path == '/v1/llm/completions-stream'
  value: post_/v1/llm/completions-stream
- condition: request.method == 'POST' && request.url_path == '/v1/llm/completions-sync'
  value: post_/v1/llm/completions-sync
- condition: request.method == 'GET' && request.url_path == '/v1/llm/fine-tunes'
  value: get_/v1/llm/fine-tunes
- condition: request.method == 'POST' && request.url_path == '/v1/llm/fine-tunes'
  value: post_/v1/llm/fine-tunes
- condition: request.method == 'GET' && request.url_path.matches('^/v1/llm/fine-tunes/[[:alnum:]-_]*$')
  value: get_/v1/llm/fine-tunes/_fine_tune_id
- condition: request.method == 'PUT' && request.url_path.matches('^/v1/llm/fine-tunes/[[:alnum:]-_]*/cancel$')
  value: put_/v1/llm/fine-tunes/_fine_tune_id/cancel
- condition: request.method == 'GET' && request.url_path.matches('^/v1/llm/fine-tunes/[[:alnum:]-_]*/events$')
  value: get_/v1/llm/fine-tunes/_fine_tune_id/events
- condition: request.method == 'GET' && request.url_path == '/v1/llm/model-endpoints'
  value: get_/v1/llm/model-endpoints
- condition: request.method == 'POST' && request.url_path == '/v1/llm/model-endpoints'
  value: post_/v1/llm/model-endpoints
- condition: request.method == 'POST' && request.url_path == '/v1/llm/model-endpoints/download'
  value: post_/v1/llm/model-endpoints/download
- condition: request.method == 'DELETE' && request.url_path.matches('^/v1/llm/model-endpoints/[[:alnum:]-_]*$')
  value: delete_/v1/llm/model-endpoints/_model_endpoint_name
- condition: request.method == 'GET' && request.url_path.matches('^/v1/llm/model-endpoints/[[:alnum:]-_]*$')
  value: get_/v1/llm/model-endpoints/_model_endpoint_name
- condition: request.method == 'GET' && request.url_path == '/v1/model-bundles'
  value: get_/v1/model-bundles
- condition: request.method == 'POST' && request.url_path == '/v1/model-bundles'
  value: post_/v1/model-bundles
- condition: request.method == 'POST' && request.url_path == '/v1/model-bundles/clone-with-changes'
  value: post_/v1/model-bundles/clone-with-changes
- condition: request.method == 'GET' && request.url_path == '/v1/model-bundles/latest'
  value: get_/v1/model-bundles/latest
- condition: request.method == 'GET' && request.url_path.matches('^/v1/model-bundles/[[:alnum:]-_]*$')
  value: get_/v1/model-bundles/_model_bundle_id
- condition: request.method == 'GET' && request.url_path == '/v1/model-endpoints'
  value: get_/v1/model-endpoints
- condition: request.method == 'POST' && request.url_path == '/v1/model-endpoints'
  value: post_/v1/model-endpoints
- condition: request.method == 'GET' && request.url_path == '/v1/model-endpoints-api'
  value: get_/v1/model-endpoints-api
- condition: request.method == 'GET' && request.url_path == '/v1/model-endpoints-schema.json'
  value: get_/v1/model-endpoints-schema.json
- condition: request.method == 'DELETE' && request.url_path.matches('^/v1/model-endpoints/[[:alnum:]-_]*$')
  value: delete_/v1/model-endpoints/_model_endpoint_id
- condition: request.method == 'GET' && request.url_path.matches('^/v1/model-endpoints/[[:alnum:]-_]*$')
  value: get_/v1/model-endpoints/_model_endpoint_id
- condition: request.method == 'PUT' && request.url_path.matches('^/v1/model-endpoints/[[:alnum:]-_]*$')
  value: put_/v1/model-endpoints/_model_endpoint_id
- condition: request.method == 'POST' && request.url_path == '/v1/streaming-tasks'
  value: post_/v1/streaming-tasks
- condition: request.method == 'POST' && request.url_path == '/v1/sync-tasks'
  value: post_/v1/sync-tasks
- condition: request.method == 'GET' && request.url_path == '/v1/triggers'
  value: get_/v1/triggers
- condition: request.method == 'POST' && request.url_path == '/v1/triggers'
  value: post_/v1/triggers
- condition: request.method == 'DELETE' && request.url_path.matches('^/v1/triggers/[[:alnum:]-_]*$')
  value: delete_/v1/triggers/_trigger_id
- condition: request.method == 'GET' && request.url_path.matches('^/v1/triggers/[[:alnum:]-_]*$')
  value: get_/v1/triggers/_trigger_id
- condition: request.method == 'PUT' && request.url_path.matches('^/v1/triggers/[[:alnum:]-_]*$')
  value: put_/v1/triggers/_trigger_id
- condition: request.method == 'GET' && request.url_path == '/v2/model-bundles'
  value: get_/v2/model-bundles
- condition: request.method == 'POST' && request.url_path == '/v2/model-bundles'
  value: post_/v2/model-bundles
- condition: request.method == 'POST' && request.url_path == '/v2/model-bundles/clone-with-changes'
  value: post_/v2/model-bundles/clone-with-changes
- condition: request.method == 'GET' && request.url_path == '/v2/model-bundles/latest'
  value: get_/v2/model-bundles/latest
- condition: request.method == 'GET' && request.url_path.matches('^/v2/model-bundles/[[:alnum:]-_]*$')
  value: get_/v2/model-bundles/_model_bundle_id
{{- end -}}
