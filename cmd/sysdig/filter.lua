args = {}

function on_init()
  fd_name = chisel.request_field("fd.name")
  exe_name = chisel.request_field("proc.exepath")
  arg_path = chisel.request_field("evt.arg.path")

  -- same as PATH_MAX
  sysdig.set_snaplen(4096)
  chisel.set_filter("evt.type in ('execve', 'openat', 'open', 'rename', 'renameat', 'stat', 'lstat', 'chmod', 'fchmodat', 'chown', 'access', 'chdir')")
  return true
end

paths = {}

file = io.open("/rootfs/.sysdig/logs", "w+")

function process_field(field)
  local path = evt.field(field)
  if path == nil or path == "<NA>" then
    return
  end
  if paths[path] == nil then
    if file == nil then
      print(path)
    else
      file:write(path)
      file:write("\0")
      file:flush()
    end
    paths[path] = true
  end
end

function on_event()
  process_field(arg_path)
  process_field(exe_name)
  process_field(fd_name)
  return true
end
