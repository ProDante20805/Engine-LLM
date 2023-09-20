"""Model Bundle v2 routes for the hosted model inference service."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from model_engine_server.api.dependencies import (
    ExternalInterfaces,
    get_external_interfaces,
    get_external_interfaces_read_only,
    verify_authentication,
)
from model_engine_server.common.datadog_utils import add_trace_resource_name
from model_engine_server.common.dtos.model_bundles import (
    CloneModelBundleV2Request,
    CreateModelBundleV2Request,
    CreateModelBundleV2Response,
    ListModelBundlesV2Response,
    ModelBundleOrderBy,
    ModelBundleV2Response,
)
from model_engine_server.core.auth.authentication_repository import User
from model_engine_server.core.loggers import filename_wo_ext, make_logger
from model_engine_server.domain.exceptions import (
    DockerImageNotFoundException,
    ObjectHasInvalidValueException,
    ObjectNotAuthorizedException,
    ObjectNotFoundException,
)
from model_engine_server.domain.use_cases.model_bundle_use_cases import (
    CloneModelBundleV2UseCase,
    CreateModelBundleV2UseCase,
    GetLatestModelBundleByNameV2UseCase,
    GetModelBundleByIdV2UseCase,
    ListModelBundlesV2UseCase,
)

model_bundle_router_v2 = APIRouter(prefix="/v2")
logger = make_logger(filename_wo_ext(__name__))


@model_bundle_router_v2.post("/model-bundles", response_model=CreateModelBundleV2Response)
async def create_model_bundle(
    request: CreateModelBundleV2Request,
    auth: User = Depends(verify_authentication),
    external_interfaces: ExternalInterfaces = Depends(get_external_interfaces),
) -> CreateModelBundleV2Response:
    """
    Creates a ModelBundle for the current user.
    """
    logger.info(f"POST /model-bundles with {request} for {auth}")
    add_trace_resource_name("model_bundles_post")
    try:
        use_case = CreateModelBundleV2UseCase(
            model_bundle_repository=external_interfaces.model_bundle_repository,
            docker_repository=external_interfaces.docker_repository,
            model_primitive_gateway=external_interfaces.model_primitive_gateway,
        )
        return await use_case.execute(user=auth, request=request)
    except ObjectNotAuthorizedException as exc:  # pragma: no cover
        raise HTTPException(
            status_code=403,
            detail="User is not authorized to create model bundle with the specified settings.",
        ) from exc
    except DockerImageNotFoundException as exc:
        raise HTTPException(
            status_code=400,
            detail="The specified custom Docker image could not be found.",
        ) from exc
    except ObjectHasInvalidValueException as exc:
        raise HTTPException(
            status_code=400,
            detail=f"The user specified an invalid value: {exc}",
        ) from exc


@model_bundle_router_v2.post(
    "/model-bundles/clone-with-changes", response_model=CreateModelBundleV2Response
)
async def clone_model_bundle_with_changes(
    request: CloneModelBundleV2Request,
    auth: User = Depends(verify_authentication),
    external_interfaces: ExternalInterfaces = Depends(get_external_interfaces),
) -> CreateModelBundleV2Response:
    """
    Creates a ModelBundle by cloning an existing one and then applying changes on top.
    """
    add_trace_resource_name("model_bundles_clone")
    try:
        use_case = CloneModelBundleV2UseCase(
            model_bundle_repository=external_interfaces.model_bundle_repository,
        )
        return await use_case.execute(user=auth, request=request)
    except (ObjectNotAuthorizedException, ObjectNotFoundException) as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Model Bundle {request.original_model_bundle_id}  was not found.",
        ) from exc


@model_bundle_router_v2.get("/model-bundles", response_model=ListModelBundlesV2Response)
async def list_model_bundles(
    model_name: Optional[str] = Query(default=None),
    order_by: Optional[ModelBundleOrderBy] = Query(default=None),
    auth: User = Depends(verify_authentication),
    external_interfaces: ExternalInterfaces = Depends(get_external_interfaces_read_only),
) -> ListModelBundlesV2Response:
    """
    Lists the ModelBundles owned by the current owner.
    """
    add_trace_resource_name("model_bundles_get")
    logger.info(f"GET /model-bundles?model_name={model_name}&order_by={order_by} for {auth}")
    use_case = ListModelBundlesV2UseCase(
        model_bundle_repository=external_interfaces.model_bundle_repository
    )
    return await use_case.execute(user=auth, model_name=model_name, order_by=order_by)


@model_bundle_router_v2.get("/model-bundles/latest", response_model=ModelBundleV2Response)
async def get_latest_model_bundle(
    model_name: str,
    auth: User = Depends(verify_authentication),
    external_interfaces: ExternalInterfaces = Depends(get_external_interfaces_read_only),
) -> ModelBundleV2Response:
    """
    Gets the latest Model Bundle with the given name owned by the current owner.
    """
    add_trace_resource_name("model_bundles_latest_get")
    logger.info(f"GET /model-bundles/latest?model_name={model_name} for {auth}")
    try:
        use_case = GetLatestModelBundleByNameV2UseCase(
            model_bundle_repository=external_interfaces.model_bundle_repository
        )
        return await use_case.execute(user=auth, model_name=model_name)
    except (ObjectNotFoundException, ObjectNotAuthorizedException) as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Model Bundle {model_name}  was not found.",
        ) from exc


@model_bundle_router_v2.get(
    "/model-bundles/{model_bundle_id}", response_model=ModelBundleV2Response
)
async def get_model_bundle(
    model_bundle_id: str,
    auth: User = Depends(verify_authentication),
    external_interfaces: ExternalInterfaces = Depends(get_external_interfaces_read_only),
) -> ModelBundleV2Response:
    """
    Gets the details for a given ModelBundle owned by the current owner.
    """
    add_trace_resource_name("model_bundles_id_get")
    logger.info(f"GET /model-bundles/{model_bundle_id} for {auth}")
    try:
        use_case = GetModelBundleByIdV2UseCase(
            model_bundle_repository=external_interfaces.model_bundle_repository
        )
        return await use_case.execute(user=auth, model_bundle_id=model_bundle_id)
    except (ObjectNotFoundException, ObjectNotAuthorizedException) as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Model Bundle {model_bundle_id}  was not found.",
        ) from exc
