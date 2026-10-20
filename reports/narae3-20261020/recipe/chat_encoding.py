"""Native full-chat tokenization, with loss on every correct assistant answer only."""
def encode_dialogue(tokenizer,row,max_length=2048):
    messages=[{"role":m["role"],"content":m["content"]} for m in row["messages"]]
    text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=False,enable_thinking=False)
    encoded=tokenizer(text,add_special_tokens=False,return_offsets_mapping=True)
    ids=encoded["input_ids"];offsets=encoded["offset_mapping"]
    if len(ids)>max_length:raise ValueError(f"No truncation: {row['id']} {len(ids)} > {max_length}")
    labels=[-100]*len(ids);spans=[]
    for i,message in enumerate(row["messages"]):
        if message["role"]!="assistant" or not message.get("loss",True):continue
        prefix=tokenizer.apply_chat_template(messages[:i],tokenize=False,add_generation_prompt=True,enable_thinking=False)
        assert text.startswith(prefix),row["id"]
        target=message["content"]+tokenizer.eos_token
        start,end=len(prefix),len(prefix)+len(target)
        assert text[start:end]==target,row["id"]
        indices=[n for n,(a,b) in enumerate(offsets) if a>=start and b<=end and b>a]
        assert indices and indices==list(range(indices[0],indices[-1]+1)),row["id"]
        assert tokenizer.decode([ids[n] for n in indices])==target,row["id"]
        for n in indices:labels[n]=ids[n]
        spans.append({"message":i,"first_token":indices[0],"last_token":indices[-1],"target":target})
    assert spans and sum(v!=-100 for v in labels)>0,row["id"]
    return ids,labels,spans
