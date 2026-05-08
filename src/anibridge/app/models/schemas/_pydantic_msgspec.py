"""Pydantic helpers for msgspec structs."""

from typing import Any

import msgspec
from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class PydanticMsgspecMixin:
    """Allow msgspec structs to participate in Pydantic model schemas."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        dict_schema = handler.generate_schema(dict[str, Any])

        def _convert(value: Any) -> Any:
            if isinstance(value, cls):
                return value
            return msgspec.convert(value, type=cls)

        object_schema = core_schema.no_info_after_validator_function(
            _convert,
            dict_schema,
        )

        return core_schema.json_or_python_schema(
            json_schema=object_schema,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), object_schema]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: msgspec.to_builtins(value),
                return_schema=dict_schema,
                when_used="always",
            ),
        )
