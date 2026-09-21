"""
Kiểm tra các module strategies/_legacy/* còn KHỚP NGUYÊN VĂN với notebook gốc (so hash từng cell / từng hàm S7).

Chạy:  python tools/verify_extraction.py --notebooks /đường/dẫn/notebooks
Thoát mã 0 nếu mọi thứ khớp; mã 1 nếu có cell bị sửa/thiếu.
"""
import argparse, ast, hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_legacy import SPECS, S7_NB, S7_PICK, cell_src

def h(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()

def main(nb_dir, leg_dir):
    bad = 0
    for key, spec in SPECS.items():
        nb = json.load(open(os.path.join(nb_dir, spec["nb"]), encoding="utf-8"))
        text = open(os.path.join(leg_dir, f"{key}_legacy.py"), encoding="utf-8").read()
        for idx in spec["cells"]:
            if cell_src(nb["cells"][idx]) not in text:
                print(f"[{key}] cell {idx}: KHÁC notebook gốc"); bad += 1
        print(f"[{key}] {len(spec['cells'])} cells kiểm tra")
    nb = json.load(open(os.path.join(nb_dir, S7_NB), encoding="utf-8"))
    text = open(os.path.join(leg_dir, "s07_legacy.py"), encoding="utf-8").read()
    n = 0
    for idx, pick in S7_PICK.items():
        src = cell_src(nb["cells"][idx]); tree = ast.parse(src)
        want = set(pick.get("funcs", [])) | set(pick.get("assign", []))
        for node in tree.body:
            nm = node.name if isinstance(node, ast.FunctionDef) else (getattr(node.targets[0], "id", None) if isinstance(node, ast.Assign) else None)
            if nm in want:
                n += 1
                if ast.get_source_segment(src, node) not in text:
                    print(f"[s07] {idx}:{nm}: KHÁC notebook gốc"); bad += 1
    print(f"[s07] {n} đối tượng kiểm tra")
    print("KẾT QUẢ:", "TẤT CẢ KHỚP NGUYÊN VĂN" if not bad else f"{bad} SAI LỆCH")
    return 1 if bad else 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--notebooks", required=True)
    ap.add_argument("--legacy", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "strategies", "_legacy"))
    a = ap.parse_args(); sys.exit(main(a.notebooks, a.legacy))
