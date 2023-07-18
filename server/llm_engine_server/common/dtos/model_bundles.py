"""
Contains various input and output types relating to Model Bundles for the server.
"""
import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from llm_engine_server.domain.entities import (
    ModelBundleEnvironmentParams,
    ModelBundleFlavors,
    ModelBundlePackagingType,
)
from pydantic import BaseModel, Field


class CreateModelBundleV1Request(BaseModel):
    """
    Request object for creating a Model Bundle.
    """

    name: str
    location: str
    requirements: List[str]
    env_params: ModelBundleEnvironmentParams
    packaging_type: ModelBundlePackagingType
    metadata: Optional[Dict[str, Any]]
    app_config: Optional[Dict[str, Any]]
    schema_location: Optional[str]


class CloneModelBundleV1Request(BaseModel):
    """
    Request object for cloning a Model Bundle from another one.
    """

    original_model_bundle_id: str
    """
    The ID of the ModelBundle to copy from.
    """

    new_app_config: Optional[Dict[str, Any]]
    """
    The app_config of the new ModelBundle. If not specified, then the new ModelBundle will use the same app_config
    as the original.
    """


class CreateModelBundleV1Response(BaseModel):
    """
    Response object for creating a Model Bundle.
    """

    model_bundle_id: str


class ModelBundleV1Response(BaseModel):
    """
    Response object for a single Model Bundle.
    """

    id: str
    name: str
    location: str
    requirements: List[str]
    env_params: ModelBundleEnvironmentParams
    packaging_type: ModelBundlePackagingType
    metadata: Dict[str, Any]
    app_config: Optional[Dict[str, Any]]
    created_at: datetime.datetime
    model_artifact_ids: List[str]
    schema_location: Optional[str]

    class Config:
        """
        ModelBundleResponse Config class.
        """

        orm_mode = True


class ListModelBundlesV1Response(BaseModel):
    """
    Response object for listing Model Bundles.
    """

    model_bundles: List[ModelBundleV1Response]


class CreateModelBundleV2Request(BaseModel):
    """
    Request object for creating a Model Bundle.
    """

    name: str
    metadata: Optional[Dict[str, Any]]
    schema_location: str
    flavor: ModelBundleFlavors = Field(..., discriminator="flavor")


class CloneModelBundleV2Request(BaseModel):
    """
    Request object for cloning a Model Bundle from another one.
    """

    original_model_bundle_id: str
    """
    The ID of the ModelBundle to copy from.
    """

    new_app_config: Optional[Dict[str, Any]]
    """
    The app_config of the new ModelBundle. If not specified, then the new ModelBundle will use the same app_config
    as the original.
    """


class CreateModelBundleV2Response(BaseModel):
    """
    Response object for creating a Model Bundle.
    """

    model_bundle_id: str


class ModelBundleV2Response(BaseModel):
    """
    Response object for a single Model Bundle.
    """

    id: str
    name: str
    metadata: Dict[str, Any]
    created_at: datetime.datetime
    model_artifact_ids: List[str]
    schema_location: Optional[str]
    flavor: ModelBundleFlavors = Field(..., discriminator="flavor")

    class Config:
        """
        ModelBundleResponse Config class.
        """

        orm_mode = True


class ListModelBundlesV2Response(BaseModel):
    """
    Response object for listing Model Bundles.
    """

    model_bundles: List[ModelBundleV2Response]


class ModelBundleOrderBy(str, Enum):
    """
    The canonical list of possible orderings of Model Bundles.
    """

    NEWEST = "newest"
    OLDEST = "oldest"
