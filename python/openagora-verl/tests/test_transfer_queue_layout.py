"""Tests for TransferQueue tensor layout conversion."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

torch = pytest.importorskip("torch", reason="torch required for layout tests")

from openagora_verl.transfer_queue._tensor_layout import (  # noqa: E402
    FORCE_NESTED_FIELDS,
    FORCE_PADDED_FIELDS,
    convert_tq_tensordict,
    tensor_to_nested,
    tensor_to_padded,
)


class TestTensorToPadded:
    def test_basic(self):
        values = [torch.tensor([1, 2]), torch.tensor([3, 4, 5])]
        out = tensor_to_padded(values)
        assert out.shape == (2, 3)
        assert out[0, 0].item() == 1
        assert out[0, 2].item() == 0
        assert out[1, 2].item() == 5

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            tensor_to_padded([])


class TestTensorToNested:
    def test_basic(self):
        values = [torch.tensor([1, 2]), torch.tensor([3, 4, 5])]
        out = tensor_to_nested(values)
        assert out.is_nested
        assert out.layout == torch.jagged
        assert out.numel() == 5


class TestConvertTQTensorDict:
    def test_prompts_responses_nested_attention_mask_padded(self):
        from tensordict import TensorDict

        prompts = torch.tensor([[0, 1, 2], [0, 0, 3]])
        responses = torch.tensor([[4, 5, 0], [6, 7, 8]])
        attention_mask = torch.tensor([[1, 1, 1, 1, 1, 0], [1, 1, 1, 1, 1, 1]])

        td = TensorDict(
            {
                "prompts": prompts,
                "responses": responses,
                "attention_mask": attention_mask,
            },
            batch_size=(2,),
        )

        out = convert_tq_tensordict(td)

        assert out["prompts"].is_nested
        assert out["responses"].is_nested
        assert not out["attention_mask"].is_nested
        assert out["attention_mask"].shape == (2, 6)

    def test_fixed_length_field_stays_padded(self):
        from tensordict import TensorDict

        rewards = torch.tensor([[1.0, 0.0], [0.5, 0.5]])
        td = TensorDict({"rewards": rewards}, batch_size=(2,))
        out = convert_tq_tensordict(td)
        assert not out["rewards"].is_nested
        assert out["rewards"].shape == (2, 2)

    def test_variable_length_field_becomes_nested(self):
        from tensordict import TensorDict

        values = torch.tensor([[1, 2, 0], [3, 0, 0]])
        td = TensorDict({"custom_field": values}, batch_size=(2,))
        out = convert_tq_tensordict(td)
        assert out["custom_field"].is_nested

    def test_force_constants(self):
        assert "prompts" in FORCE_NESTED_FIELDS
        assert "responses" in FORCE_NESTED_FIELDS
        assert "attention_mask" in FORCE_PADDED_FIELDS

    def test_empty_tensordict_unchanged(self):
        from tensordict import TensorDict

        td = TensorDict({}, batch_size=(0,))
        out = convert_tq_tensordict(td)
        assert out.batch_size == (0,)

    def test_already_nested_left_alone(self):
        from tensordict import TensorDict

        nested = torch.nested.as_nested_tensor(
            [torch.tensor([1, 2]), torch.tensor([3])], layout=torch.jagged
        )
        td = TensorDict({"prompts": nested}, batch_size=(2,))
        out = convert_tq_tensordict(td)
        assert out["prompts"].is_nested
