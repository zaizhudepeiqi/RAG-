from collections.abc import Sequence
from uuid import UUID, uuid5

from app.modules.chunking.domain import NormalizedUnit, TokenCount
from app.modules.chunking.strategies import ChunkingContext

GENERATION_ID = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")


class CharacterTokenCounter:
    code = "character_test"
    version = "1"
    estimated = False

    def count(self, text: str) -> TokenCount:
        return TokenCount(len(text), self.code, self.version, self.estimated)

    def encode(self, text: str) -> Sequence[int]:
        return tuple(ord(character) for character in text)

    def decode(self, tokens: Sequence[int]) -> str:
        return "".join(chr(token) for token in tokens)


def make_context(algorithm_version: str = "test-v1") -> ChunkingContext:
    return ChunkingContext(
        generation_id=GENERATION_ID,
        parsed_source_version_id=VERSION_ID,
        algorithm_version=algorithm_version,
        counter=CharacterTokenCounter(),
    )


def make_unit(
    text: str,
    *,
    index: int = 0,
    heading_path: tuple[str, ...] = (),
    page_numbers: tuple[int, ...] = (1,),
    searchable_text: str | None = None,
) -> NormalizedUnit:
    block_id = uuid5(VERSION_ID, f"block:{index}")
    asset_id = uuid5(VERSION_ID, f"asset:{index}")
    return NormalizedUnit(
        parsed_source_version_id=VERSION_ID,
        order_index=index,
        text=text,
        searchable_text=searchable_text or text,
        block_type="paragraph",
        source_block_ids=(block_id,),
        asset_ids=(asset_id,),
        heading_path=heading_path,
        page_numbers=page_numbers,
        bounding_boxes=({"page": page_numbers[0]},) if page_numbers else (),
    )
