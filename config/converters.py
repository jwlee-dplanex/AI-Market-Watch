import uuid
import shortuuid


class ShortUUIDConverter:
    # shortuuid base57 alphabet, 22자 고정
    regex = r'[23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]{22}'

    def to_python(self, value: str) -> uuid.UUID:
        return shortuuid.decode(value)

    def to_url(self, value) -> str:
        if isinstance(value, uuid.UUID):
            return shortuuid.encode(value)
        return str(value)
