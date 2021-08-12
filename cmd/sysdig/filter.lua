args = {}

function on_init()
  fd_name = chisel.request_field("fd.name")
  -- same as PATH_MAX
  sysdig.set_snaplen(4096)
  chisel.set_filter("(evt.type=openat or evt.type=open or evt.type=rename or evt.type=renameat) and evt.dir=< and not fd.name contains /proc and not fd.name contains /sys")
  return true
end

paths = {}

file = io.open("/rootfs/.sysdig/logs", "w+")

function on_event()
  local path = evt.field(fd_name)
  if path ~= nil and paths[path] == nil then
    file:write(path)
    file:write("\0")
    file:flush()
    paths[path] = true
  end
  return true
end
