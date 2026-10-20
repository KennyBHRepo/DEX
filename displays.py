"""Map the engine's zero-based canvas into macOS's global display coordinates."""
def bounds(rects):
    x = min(r[0] for r in rects); y = min(r[1] for r in rects)
    return x, y, max(r[0]+r[2] for r in rects)-x, max(r[1]+r[3] for r in rects)-y


def nearest_point(x, y, rects):
    points = [(min(max(x, rx), rx+w-1), min(max(y, ry), ry+h-1)) for rx,ry,w,h in rects]
    return min(points, key=lambda p: (p[0]-x)**2+(p[1]-y)**2)


def active_rects(quartz):
    error, ids, count = quartz.CGGetActiveDisplayList(32, None, None)
    if error or not count:
        ids = [quartz.CGMainDisplayID()]
    rects = []
    for ident in ids:
        b = quartz.CGDisplayBounds(ident)
        if b.size.width > 0 and b.size.height > 0:
            rects.append((b.origin.x, b.origin.y, b.size.width, b.size.height))
    return rects or [(0, 0, 1920, 1080)]
