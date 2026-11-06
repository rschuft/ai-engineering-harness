# Sourced by the publication-safety gate hooks. Locates CPython >= 3.12 and runs
# tools/publication_gate.py; all logic lives there. Fails closed: when Python or
# the gate cannot be found, the hook blocks. See docs/development.md,
# "Publication-safety gate".

run_gate() {
    top=$(git rev-parse --show-toplevel) || {
        echo "publication-gate: cannot locate the repository root; blocking (fail closed)" >&2
        exit 2
    }
    gate="$top/tools/publication_gate.py"
    if [ ! -f "$gate" ]; then
        echo "publication-gate: tools/publication_gate.py is missing; blocking (fail closed)" >&2
        exit 2
    fi
    for candidate in python3 python "py -3"; do
        # $candidate is split on purpose ("py -3").
        if $candidate -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
                </dev/null >/dev/null 2>&1; then
            exec $candidate -I -B "$gate" "$@"
        fi
    done
    echo "publication-gate: no CPython >= 3.12 found (tried python3, python, py -3); blocking (fail closed)" >&2
    exit 2
}
