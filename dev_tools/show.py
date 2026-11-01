import json,sys
items={json.loads(l)["id"]:json.loads(l) for l in open("eval/public_eval.jsonl")}
for l in open(sys.argv[1] if len(sys.argv)>1 else "results/per_question.jsonl"):
    r=json.loads(l); it=items[r["id"]]
    flag="OK " if r["score"]>=0.99 else (".. " if r["score"]>0 else "XX ")
    print(f'{flag}{r["id"]} {r["score"]:.2f} [{r["category"]}] {it["question"]}')
    if r["score"]<0.99:
        print(f'     must={it["must_include"]} not={it["must_not_include"]} traps={r["trap_hits"]} src_hit={r["source_hit"]}')
        print(f'     ANS: {r["answer"]["text"][:260]!r}')
        print(f'     SRC: {[s["url"] for s in r["answer"]["sources"]][:3]}')
