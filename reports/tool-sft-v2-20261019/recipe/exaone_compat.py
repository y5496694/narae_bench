"""Bridge the pinned EXAONE source to Transformers 5.20 without changing weights."""
import inspect
import sys


def configure_exaone(model):
    model.transformer._input_embed_layer = "wte"
    assert model.get_input_embeddings() is model.transformer.wte
    assert model.get_output_embeddings() is model.lm_head
    assert model.lm_head.weight is model.transformer.wte.weight
    module = sys.modules[model.__class__.__module__]
    original = module.create_causal_mask
    signature = inspect.signature(original)
    if "inputs_embeds" in signature.parameters and "input_embeds" not in signature.parameters:
        def create_causal_mask_compat(**kwargs):
            kwargs["inputs_embeds"] = kwargs.pop("input_embeds")
            # The current API derives its position offset from DynamicCache.
            kwargs.pop("cache_position", None)
            return original(**kwargs)
        module.create_causal_mask = create_causal_mask_compat
    return model
