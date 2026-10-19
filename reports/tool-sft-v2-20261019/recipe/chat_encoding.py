"""Mask every observed/user token and incorrect context-only assistant turn."""
def encode_dialogue(tokenizer, row, max_length=2048):
    assert row["messages"][-1]["role"] == "assistant" and row["messages"][-1].get("loss", True)
    assert all(not m.get("loss", False) for m in row["messages"][:-1] if m["role"] == "assistant")
    messages = [{"role": m["role"], "content": m["content"]} for m in row["messages"][:-1]]
    prefix = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    prefix_ids = tokenizer.encode(prefix, add_special_tokens=False)
    answer_ids = tokenizer.encode(row["messages"][-1]["content"], add_special_tokens=False) + [tokenizer.eos_token_id]
    ids = prefix_ids + answer_ids
    if len(ids) > max_length:
        raise ValueError(f"Too long, no truncation: {row['id']} {len(ids)} > {max_length}")
    labels = [-100]*len(prefix_ids) + answer_ids
    if not any(label != -100 for label in labels):
        raise ValueError(f"No assistant targets: {row['id']}")
    return ids, labels
