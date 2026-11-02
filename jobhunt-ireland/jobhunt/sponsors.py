"""Irish employment-permit sponsor lookup (DETE permits issued to companies, 2025 + Jan-Sep 2026).

A permit count signals that an employer sponsors permits. It is not a per-company Critical Skills count.
"""
import os
import re

from .util import DATA, load_json, norm_company

AGENCY = re.compile(r"recruit|resourcing|staffing|personnel|\bcpl\b|hays|sigmar|morgan mckinley|robert walters|"
                    r"collins mcnicholas|harvey nash|reperio|jacksonstone|staffline|mpg|abbey|osborne|lincoln|"
                    r"head ?hunt|talent|search|careers|jobgether|stelfox|hamilton barnes|fruition|prism digital", re.I)


class Sponsors:
    def __init__(self, path=None):
        path = path or os.path.join(DATA, "sponsors.json")
        self.idx = {}
        self.brands = []
        if not os.path.exists(path):
            return
        for b in load_json(path)["brands"]:
            info = {k: b[k] for k in ("brand", "rank", "permits_2025", "permits_2026", "total", "category")}
            self.brands.append(info)
            names = [b["brand"], *b.get("entities", []), *b["brand"].replace("(", "/").replace(")", "").split("/")]
            for name in names:
                k = norm_company(name)
                if len(k) >= 3:
                    self.idx.setdefault(k, info)

    def lookup(self, company):
        k = norm_company(company)
        if not k:
            return None
        if k in self.idx:
            return self.idx[k]
        for name, info in self.idx.items():  # "amazon" matches "amazon aws", "dell" matches "dell technologies"
            if len(name) >= 4 and (k.startswith(name + " ") or name.startswith(k + " ")):
                return info
        return None

    @staticmethod
    def is_agency(company):
        return bool(AGENCY.search(company or ""))
