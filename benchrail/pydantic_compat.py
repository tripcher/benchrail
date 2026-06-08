from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import VERSION as PYDANTIC_VERSION

IS_PYDANTIC_V1 = PYDANTIC_VERSION.startswith("1.")
ModelT = TypeVar("ModelT", bound="BaseModel")

if TYPE_CHECKING or not IS_PYDANTIC_V1:
    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

    class AllowExtraBaseModel(BaseModel):
        model_config = ConfigDict(extra="allow")

else:
    from pydantic import BaseModel as PydanticBaseModel
    from pydantic import Field, root_validator, validator

    class BaseModel(PydanticBaseModel):
        @classmethod
        def model_validate(cls: type[ModelT], obj: Any) -> ModelT:
            return cls.parse_obj(obj)

        def model_dump(self, **kwargs: Any) -> dict[str, Any]:
            return self.dict(**kwargs)

        def model_dump_json(self, **kwargs: Any) -> str:
            return self.json(**kwargs)

        def model_copy(
            self: ModelT,
            *,
            update: dict[str, Any] | None = None,
            deep: bool = False,
        ) -> ModelT:
            return self.copy(update=update, deep=deep)

    def field_validator(*fields: str) -> Any:
        return validator(*fields, allow_reuse=True)

    def model_validator(*, mode: str) -> Any:
        if mode != "after":
            raise NotImplementedError("Only model_validator(mode='after') is supported")

        def decorator(fn: Any) -> Any:
            @root_validator(allow_reuse=True, skip_on_failure=True)
            def wrapped(cls: type[BaseModel], values: dict[str, Any]) -> dict[str, Any]:
                model = cls.construct(**values)
                result = fn(model)
                if isinstance(result, cls):
                    return result.__dict__
                return values

            return wrapped

        return decorator

    class AllowExtraBaseModel(BaseModel):
        class Config:
            extra = "allow"


__all__ = [
    "AllowExtraBaseModel",
    "BaseModel",
    "Field",
    "field_validator",
    "model_validator",
]
