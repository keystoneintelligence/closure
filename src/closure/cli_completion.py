"""Opt-in shell completion. Candidate lookup reads contracts, never runs analyses."""
from .cli_args import COMMANDS, make_parser, project_path
from .io import ClosureError
from .project import Project


SCRIPTS = {
    "bash": r'''# Load for this session: source <(closure completion bash)
_closure_complete() {
    local candidate
    COMPREPLY=()
    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] && COMPREPLY+=("$candidate")
    done < <(closure _complete -- "${COMP_WORDS[@]:1:$COMP_CWORD}")
}
complete -o default -F _closure_complete closure
''',
    "powershell": r'''# Load for this session: closure completion powershell | Out-String | Invoke-Expression
Register-ArgumentCompleter -Native -CommandName closure,closure.exe -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $tokens = @($commandAst.CommandElements | Select-Object -Skip 1 | Where-Object { $_.Extent.StartOffset -lt $cursorPosition } | ForEach-Object {
        if ($_ -is [System.Management.Automation.Language.StringConstantExpressionAst]) { $_.Value } else { $_.Extent.Text }
    })
    if (-not $wordToComplete) { $tokens += '' }
    # JSON transport preserves an empty last word on Windows PowerShell too.
    $payload = ConvertTo-Json -InputObject @($tokens) -Compress
    $candidates = $payload | & ($commandAst.CommandElements[0].Value) _complete-json
    foreach ($candidate in $candidates) {
        if ($candidate) {
            $quoted = if ($candidate -match '[\s''"`$;|&(){}]') { "'" + $candidate.Replace("'", "''") + "'" } else { $candidate }
            [System.Management.Automation.CompletionResult]::new($quoted, $candidate, 'ParameterValue', $candidate)
        }
    }
}
''',
}


def candidates(words):
    if not words:
        words = [""]
    prefix, previous = words[-1], words[-2] if len(words) > 1 else None
    parser, parsers = make_parser()
    command, explicit, positions = None, None, []
    actions = {option: action for action in parser._actions for option in action.option_strings}
    index = 0
    while index < len(words) - 1:
        word = words[index]
        if word in actions:
            action = actions[word]
            if action.nargs != 0:
                if index + 1 < len(words) - 1:
                    if word in ("-p", "--project"):
                        explicit = words[index + 1]
                    index += 2
                    continue
                break
        elif word.startswith("--project="):
            explicit = word.split("=", 1)[1]
        elif command is None and word in COMMANDS:
            command = word
            actions.update({option: action for action in parsers[word]._actions for option in action.option_strings})
        elif not word.startswith("-"):
            positions.append(word)
        index += 1
    options = list(actions)
    choices = None
    if previous in actions and actions[previous].nargs != 0:
        choices = actions[previous].choices or []
        if previous not in ("--scenario", "--configuration"):
            return sorted(str(c) for c in choices if str(c).startswith(prefix))
    if prefix.startswith("-") and choices is None:
        return sorted(c for c in options if c.startswith(prefix))
    if command is None:
        return sorted(c for c in [*COMMANDS, "help"] if c.startswith(prefix))
    if command == "completion":
        return [c for c in SCRIPTS if c.startswith(prefix)]
    try:
        project = Project(project_path(explicit))
        if previous == "--scenario":
            choices = project.manifest.scenarios
        elif previous == "--configuration":
            choices = project.manifest.configurations
        elif command == "set" and len(positions) == 1:
            parameter = project.parameters.get(positions[0])
            choices = parameter.choices if parameter and parameter.type == "enum" else ["true", "false"] if parameter and parameter.type == "boolean" else []
        elif not positions:
            if command == "set":
                choices = project.parameters
            elif command in ("explain", "review"):
                choices = project.requirements
            elif command in ("inspect", "impact"):
                choices = project.locations.keys() | project.ports.keys()
    except (ClosureError, ValueError, OSError):
        # Completion must remain quiet in an incomplete project.
        choices = []
    return sorted(c for c in (choices or []) if c.startswith(prefix))
