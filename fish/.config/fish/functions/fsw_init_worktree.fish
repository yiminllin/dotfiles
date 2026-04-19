function fsw_init_worktree --argument-names wt
    set -l remote (git -C "$wt" remote get-url origin 2>/dev/null)
    if not string match -qr '(^|[/:])FlightSystems(\.git)?$' -- $remote
        return 0
    end

    test -f ~/.config/flightsystems/user.bazelrc; and command cp ~/.config/flightsystems/user.bazelrc "$wt"/user.bazelrc

    pushd "$wt" >/dev/null
    test -f .envrc; and direnv allow .
    bazel run //bazel/tools:bazel_env
    set -l rc $status
    popd >/dev/null

    return $rc
end
