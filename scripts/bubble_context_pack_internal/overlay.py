import re
from collections import defaultdict
from pathlib import Path

from .shared import load_json, normalize_string, unique_list_of_dicts


class OverlayManager:
    def __init__(self, repo_root, app_slug):
        self.repo_root = Path(repo_root)
        self.app_slug = app_slug
        self.overlay_root = self.repo_root / self.app_slug
        self.privacy_rules_path = self.overlay_root / "privacy_rules_as_is.json"
        self.workflow_ast_path = self.overlay_root / "backend_workflows_as_is.json"
        self.schema_prisma_path = self.overlay_root / "schema_as_is.prisma"
        self.schema_md_path = self.overlay_root / "database_schema_as_is.md"
        self.privacy_rules = load_json(self.privacy_rules_path) if self.privacy_rules_path.exists() else []
        self.workflow_ast = load_json(self.workflow_ast_path) if self.workflow_ast_path.exists() else []
        self.prisma_models = self._load_prisma_models()
        self.privacy_lookup = self._build_privacy_lookup()
        self.workflow_lookup = self._build_workflow_lookup()
        self.coverage = {
            "privacy_rules": {"matched": 0, "unmatched": 0},
            "backend_workflows_as_is": {"matched": 0, "unmatched": 0},
            "schema_prisma": {"matched": 0, "unmatched": 0},
        }
        self._matched_privacy = set()
        self._matched_workflow_ast = set()
        self._matched_prisma_models = set()

    def _display_path(self, path):
        try:
            return path.relative_to(self.repo_root).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def _load_prisma_models(self):
        models = {}
        if not self.schema_prisma_path.exists():
            return models
        for line in self.schema_prisma_path.read_text().splitlines():
            match = re.match(r"model\s+([A-Za-z0-9_]+)\s+\{", line)
            if match:
                model_name = match.group(1)
                models[normalize_string(model_name)] = model_name
        return models

    def _build_privacy_lookup(self):
        lookup = defaultdict(list)
        for item in self.privacy_rules:
            table = item.get("table")
            if not table:
                continue
            lookup[normalize_string(table)].append(item)
        return lookup

    def _build_workflow_lookup(self):
        lookup = defaultdict(list)
        for item in self.workflow_ast:
            candidates = [
                item.get("workflow_name"),
                item.get("trigger", {}).get("endpoint"),
            ]
            for candidate in candidates:
                if candidate:
                    lookup[normalize_string(candidate)].append(item)
        return lookup

    def resolve_for_entity(self, entity_type, source_key, display_name):
        links = []
        candidates = [normalize_string(source_key), normalize_string(display_name)]
        candidates = [candidate for candidate in candidates if candidate]

        if entity_type == "user_type":
            for candidate in candidates:
                for match in self.privacy_lookup.get(candidate, []):
                    links.append(
                        {
                            "kind": "privacy_rules_as_is",
                            "path": self._display_path(self.privacy_rules_path),
                            "match_key": match.get("table"),
                            "coverage": "matched",
                        }
                    )
                    self._matched_privacy.add(match.get("table"))

            for candidate in candidates:
                prisma_model = self.prisma_models.get(candidate)
                if prisma_model:
                    links.append(
                        {
                            "kind": "schema_as_is",
                            "path": self._display_path(self.schema_prisma_path),
                            "match_key": prisma_model,
                            "coverage": "matched",
                        }
                    )
                    links.append(
                        {
                            "kind": "database_schema_as_is",
                            "path": self._display_path(self.schema_md_path),
                            "match_key": prisma_model,
                            "coverage": "matched",
                        }
                    )
                    self._matched_prisma_models.add(prisma_model)
                    break

        if entity_type == "backend_workflow":
            for candidate in candidates:
                for match in self.workflow_lookup.get(candidate, []):
                    links.append(
                        {
                            "kind": "backend_workflows_as_is",
                            "path": self._display_path(self.workflow_ast_path),
                            "match_key": match.get("workflow_name"),
                            "coverage": "matched",
                        }
                    )
                    self._matched_workflow_ast.add(match.get("workflow_name"))
        return unique_list_of_dicts(links)

    def finalize_coverage(self):
        self.coverage["privacy_rules"]["matched"] = len(self._matched_privacy)
        self.coverage["privacy_rules"]["unmatched"] = max(len(self.privacy_rules) - len(self._matched_privacy), 0)
        self.coverage["backend_workflows_as_is"]["matched"] = len(self._matched_workflow_ast)
        self.coverage["backend_workflows_as_is"]["unmatched"] = max(len(self.workflow_ast) - len(self._matched_workflow_ast), 0)
        self.coverage["schema_prisma"]["matched"] = len(self._matched_prisma_models)
        self.coverage["schema_prisma"]["unmatched"] = max(len(self.prisma_models) - len(self._matched_prisma_models), 0)
        return self.coverage
