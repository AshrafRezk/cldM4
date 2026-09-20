# shellcheck shell=sh
# KEY=VALUE loader for ~/Cloudiator/.env.
#
# Do not `source` that file. zsh treats unquoted parentheses as a parse error
# (`NOMINATIM_USER_AGENT=Cloudiator/0.1 (you@example.com)` is the documented
# value), and the LaunchAgent wrapper runs under `set -e`, so a failed source
# kills the worker before uvicorn starts. This parser never evaluates the file
# as shell: no command substitution, no `$VAR` expansion, no `source` abort.
#
# Sourced by scripts/lib/common.sh (bash 3.2 on macOS) and by
# infra/launchd/run-worker.sh (zsh). Keep this POSIX.

load_env_file() {
  _cld_env_file=$1
  if [ ! -f "$_cld_env_file" ]; then
    unset _cld_env_file
    return 0
  fi

  while IFS= read -r _cld_line || [ -n "$_cld_line" ]; do
    _cld_line=${_cld_line%"$(printf '\r')"}
    # Trim leading whitespace.
    _cld_line=${_cld_line#"${_cld_line%%[![:space:]]*}"}
    case $_cld_line in
      '' | \#*) continue ;;
    esac
    case $_cld_line in
      export[\ \	]*)
        _cld_line=${_cld_line#export}
        _cld_line=${_cld_line#"${_cld_line%%[![:space:]]*}"}
        ;;
    esac
    case $_cld_line in
      *=*) ;;
      *) continue ;;
    esac

    _cld_key=${_cld_line%%=*}
    _cld_value=${_cld_line#*=}
    # Trim trailing whitespace on the key only.
    _cld_key=${_cld_key%"${_cld_key##*[![:space:]]}"}
    case $_cld_key in
      [A-Za-z_]*)
        case $_cld_key in
          *[!A-Za-z0-9_]*) continue ;;
        esac
        ;;
      *) continue ;;
    esac

    if [ "${#_cld_value}" -ge 2 ]; then
      _cld_q=${_cld_value%"${_cld_value#?}"}
      _cld_r=${_cld_value#"${_cld_value%?}"}
      if [ "$_cld_q" = "$_cld_r" ] && { [ "$_cld_q" = '"' ] || [ "$_cld_q" = "'" ]; }; then
        _cld_value=${_cld_value#?}
        _cld_value=${_cld_value%?}
      fi
    fi

    # The value is assigned literally. `export KEY=value` without quoting the
    # whole assignment would re-split on spaces and re-introduce the parse error.
    export "$_cld_key=$_cld_value"
  done < "$_cld_env_file"

  unset _cld_env_file _cld_line _cld_key _cld_value _cld_q _cld_r
  return 0
}
