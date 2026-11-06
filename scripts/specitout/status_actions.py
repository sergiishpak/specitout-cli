from __future__ import annotations

import shlex


def status_next_actions(*, readiness_state: str, is_active: bool, degraded: bool,
                        app_slug: str | None = None, version_label: str | None = None,
                        pipeline_status: str | None = None) -> list[str]:
    scope = f"--app {shlex.quote(app_slug or '<app-slug>')} --version {shlex.quote(version_label or '<version>')}"
    status = f"import status {scope}"
    resume = f"index resume {scope}"
    if readiness_state == 'ingesting' and pipeline_status == 'running':
        return [status]
    if readiness_state in {'registered', 'failed'}:
        return [f"import retry {scope}", status]
    if readiness_state in {'ingesting', 'searchable', 'embedding_pending', 'degraded'}:
        return [resume, status]
    if readiness_state == 'ready':
        actions = [f"query search {scope} --query '<query-text>'",
                   f"query entity {scope} --entity '<entity-key>'"]
        if not is_active:
            actions.insert(0, f"import activate {scope}")
        return actions
    if degraded:
        return [status]
    return [f"import list --app {shlex.quote(app_slug or '<app-slug>')}"]


def resolve_action_hints(envelope: dict, project=None) -> dict:
    """Bind known scope without guessing user inputs such as a new export's path."""
    scope = envelope.get('scope') or {}
    replacements = {'<app-slug>': scope.get('app_slug'), '<version>': scope.get('version_label')}
    actions = []
    for action in envelope.get('next_actions') or []:
        original_tokens = shlex.split(action)
        action_replacements = replacements if original_tokens[:2] != ['import', 'add'] else {'<app-slug>': scope.get('app_slug')}
        tokens = [str(action_replacements.get(token) or token) for token in original_tokens]
        start = 2 if tokens[:1] == ['--project'] else 0
        command = tokens[start:start + 2]
        versioned = command[:1] in (['query'], ['bundle'], ['index']) or command in (['import', 'status'], ['import', 'retry'], ['import', 'activate'])
        if versioned and scope.get('version_label') and '--version' not in tokens:
            tokens += ['--version', str(scope['version_label'])]
        if command == ['query', 'search'] and '--query' not in tokens:
            tokens += ['--query', '<query-text>']
        if project is not None and tokens[:1] != ['--project']:
            tokens = ['--project', str(project.root), *tokens]
        actions.append(shlex.join(tokens))
    return {**envelope, 'next_actions': actions}
