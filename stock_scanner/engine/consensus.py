"""
Meta / Consensus Engine — CHỈ ĐỌC kết quả của các strategy, KHÔNG BAO GIỜ sửa signal gốc.

Nhiệm vụ: so sánh 7 strategy, đếm đồng thuận/bất đồng, chỉ ra xung đột, và (tuỳ chọn) một điểm tổng hợp
mang tính thống kê hiển thị. "Bất đồng là thông tin có giá trị" nên luôn được liệt kê, không che giấu.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from strategies.base import (StrategyResult, BULLISH, BEARISH, ACTIVE, STRONG_BUY, BUY, WATCH, NONE,
                             SHORT, REDUCE, EXIT)


@dataclass
class Consensus:
    symbol: str
    n_active: int = 0
    n_bull: int = 0
    n_watch: int = 0
    n_none: int = 0
    n_bear: int = 0
    n_excluded: int = 0                       # FILTERED / NO_DATA / ERROR / UNSUPPORTED
    label: str = "—"
    conflict: str = ""                        # mô tả xung đột (rỗng nếu không có)
    disagreement: List[str] = field(default_factory=list)
    family_votes: Dict[str, str] = field(default_factory=dict)    # dòng A/B/C/D -> nhãn phiếu của dòng
    n_bull_families: int = 0
    n_families: int = 0
    agg_score: Optional[float] = None         # thống kê hiển thị (0–100), KHÔNG phải strategy
    lead: str = ""                            # strategy nghiêng mua có điểm cao nhất (nguồn Entry/SL/TP hiển thị)
    signals: Dict[str, str] = field(default_factory=dict)
    ai_signal: Optional[str] = None            # tín hiệu S8 (Claude AI) — luôn TÁCH RIÊNG khỏi phiếu 7-notebook
    ai_score: Optional[float] = None
    ai_note: str = ""


def _family_vote(sigs: List[str]) -> str:
    """Một dòng code = một phiếu. Nếu các thành viên không thống nhất -> 'MIXED' (không cố gộp)."""
    s = set(sigs)
    if len(s) == 1:
        return sigs[0]
    if s <= BULLISH:
        return BUY
    return "MIXED"


def compute_consensus(symbol: str, results: Dict[str, StrategyResult], families: Dict[str, str],
                      count_sids: Optional[Iterable[str]] = None) -> Consensus:
    """count_sids: tập sid được TÍNH vào đồng thuận (mặc định = tất cả trong `results`).
    Dùng để loại S8 (family 'E', không thuộc 7 notebook gốc) khỏi Bull/Families trừ khi người dùng bật.
    S8 vẫn được lưu trong `signals`/`ai_signal` để hiển thị riêng — không bị ẩn, chỉ không gộp phiếu."""
    c = Consensus(symbol=symbol)
    c.signals = {sid: r.signal for sid, r in results.items()}
    ai = {sid: r for sid, r in results.items() if families.get(sid) == "E"}
    if ai:
        r = next(iter(ai.values()))
        c.ai_signal, c.ai_score, c.ai_note = r.signal, r.score_pct, r.native_signal
    counted = set(count_sids) if count_sids is not None else set(results)
    act = {sid: r for sid, r in results.items() if r.signal in ACTIVE and sid in counted}
    c.n_active = len(act)
    c.n_excluded = len(results) - len(act)
    for r in act.values():
        if r.signal in BULLISH: c.n_bull += 1
        elif r.signal == WATCH: c.n_watch += 1
        elif r.signal in BEARISH: c.n_bear += 1
        else: c.n_none += 1

    # Phiếu theo dòng code (tránh đếm đôi S5+S6, S1+S2, S3+S4)
    fam: Dict[str, List[str]] = defaultdict(list)
    for sid, r in act.items():
        fam[families[sid]].append(r.signal)
    c.family_votes = {f: _family_vote(v) for f, v in sorted(fam.items())}
    c.n_families = len(c.family_votes)
    c.n_bull_families = sum(1 for v in c.family_votes.values() if v in BULLISH)

    if c.n_active == 0:
        c.label = "KHÔNG CÓ DỮ LIỆU"
    else:
        share = c.n_bull / c.n_active
        if c.n_bear and c.n_bull:
            c.label = "PHÂN HOÁ (có cả mua và thoát)"
        elif c.n_bear >= max(1, c.n_active // 2):
            c.label = "TIÊU CỰC"
        elif share >= 2 / 3:
            c.label = "ĐỒNG THUẬN MUA"
        elif share > 0.5:
            c.label = "NGHIÊNG MUA"
        elif c.n_bull:
            c.label = "PHÂN HOÁ (thiểu số mua)"
        elif c.n_watch:
            c.label = "THEO DÕI"
        else:
            c.label = "TRUNG LẬP"

    # Xung đột & danh sách bất đồng
    bull_ids = sorted(s for s, r in act.items() if r.signal in BULLISH)
    bear_ids = sorted(s for s, r in act.items() if r.signal in BEARISH)
    other = sorted(s for s, r in act.items() if r.signal not in BULLISH | BEARISH)
    if bull_ids and bear_ids:
        c.conflict = f"MUA ({', '.join(bull_ids)}) ⟷ THOÁT/GIẢM ({', '.join(bear_ids)})"
    elif bull_ids and other and len(bull_ids) < c.n_active:
        c.conflict = f"MUA ({', '.join(bull_ids)}) ⟷ chưa mua ({', '.join(other)})"
    for grp, ids in (("MUA", bull_ids), ("THOÁT/GIẢM", bear_ids), ("Chưa mua", other)):
        if ids:
            c.disagreement.append(f"{grp}: " + ", ".join(f"{i}={SHORT[act[i].signal]}" for i in ids))

    scores = [r.score_pct for r in act.values() if r.score_pct is not None]
    c.agg_score = round(sum(scores) / len(scores), 1) if scores else None
    lead = [r for r in act.values() if r.signal in BULLISH and r.score_pct is not None]
    if lead:
        c.lead = max(lead, key=lambda r: (r.score_pct, r.sid)).sid
    return c
