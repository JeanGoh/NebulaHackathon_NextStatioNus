"""Infer the reference validator's rule semantics from a known-good submission.

The brief leaves several rules ambiguous but ships `03_submission_sample/`,
described as "a feasible, 0-hard-violation submission". That is ground truth:
any interpretation flagging it is wrong. Rather than guessing interpretations by
hand, enumerate the whole hypothesis space and keep every configuration
consistent with the evidence.

The useful output is not just "which config works" but **which dimensions the
evidence actually pins down**. A dimension that every surviving config disagrees
on is unfalsifiable from this sample, and any choice we make there is a guess we
should say out loud rather than bury.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, fields

from .model import Instance
from .submission import Submission
from .validate import Policy, validate

# Each ambiguous rule and the values it could take.
HYPOTHESIS_SPACE = {
    "buffer_bites_platforms": [False, True],
    "buffer_pushes_carriers_only": [True, False],
    "overlap_implies_separated": [True, False],
}


@dataclass
class Calibration:
    consistent: list[dict]
    rejected: list[tuple[dict, int]]
    determined: dict[str, object]
    undetermined: dict[str, list]

    def summary(self) -> str:
        out = [f"{len(self.consistent)} of "
               f"{len(self.consistent) + len(self.rejected)} configurations are "
               f"consistent with the reference submission.", ""]
        if self.determined:
            out.append("Pinned down by the evidence:")
            for k, v in sorted(self.determined.items()):
                out.append(f"  {k} = {v}")
        if self.undetermined:
            out.append("")
            out.append("NOT determined — the sample cannot distinguish these, "
                       "so our choice is a guess:")
            for k, vals in sorted(self.undetermined.items()):
                out.append(f"  {k} could be any of {vals}")
        if self.rejected:
            out.append("")
            out.append("Ruled out (these flag the reference submission, so they "
                       "cannot be what the validator does):")
            for cfg, n in sorted(self.rejected, key=lambda r: r[1])[:8]:
                bits = ", ".join(f"{k}={v}" for k, v in sorted(cfg.items()))
                out.append(f"  {n:3d} violations  {bits}")
        return "\n".join(out)


def calibrate(inst: Instance, reference: Submission,
              scenario: str | None = None) -> Calibration:
    """Search every combination of ambiguous rules against a known-good answer."""
    names = list(HYPOTHESIS_SPACE)
    valid = {f.name for f in fields(Policy)}
    assert set(names) <= valid, f"unknown policy fields: {set(names) - valid}"

    consistent, rejected = [], []
    for combo in itertools.product(*(HYPOTHESIS_SPACE[n] for n in names)):
        cfg = dict(zip(names, combo))
        rep = validate(inst, reference, scenario, Policy(**cfg))
        # Only rules in the hypothesis space may be judged here; a violation of
        # some unrelated rule would condemn every configuration equally.
        n = len(rep.hard_violations)
        (consistent if n == 0 else rejected).append(cfg if n == 0 else (cfg, n))

    determined, undetermined = {}, {}
    for n in names:
        seen = {c[n] for c in consistent}
        if len(seen) == 1:
            determined[n] = seen.pop()
        else:
            undetermined[n] = sorted(seen, key=str)
    return Calibration(consistent, rejected, determined, undetermined)
