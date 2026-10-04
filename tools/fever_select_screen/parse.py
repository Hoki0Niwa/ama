"""Read the dropset bar: white blobs separated by erosion, then grouped into pieces."""
from PIL import Image
import numpy as np, glob, sys
from scipy import ndimage

def blobs(path):
    a = np.asarray(Image.open(path).convert('RGB').resize((740*3, 340*3), Image.LANCZOS)).astype(int)[148*3:232*3, 0:480*3]
    white = a.min(axis=2) > 215
    core = ndimage.binary_erosion(white, iterations=5)
    lab, n = ndimage.label(core)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        h = (sl[0].stop - sl[0].start + 10) / 3; w = (sl[1].stop - sl[1].start + 10) / 3
        if h < 8 or w < 8 or h > 50 or w > 50: continue
        # red outline nearby
        y0, y1, x0, x1 = max(sl[0].start-22,0), sl[0].stop+22, max(sl[1].start-22,0), sl[1].stop+22
        box = a[y0:y1, x0:x1]
        if ((box[...,0] > 190) & (box[...,1] < 90) & (box[...,2] < 90)).sum() < 150: continue
        cx, cy = (sl[1].start+sl[1].stop)/6, (sl[0].start+sl[0].stop)/6
        if abs(cy - (46 - 0.065*cx)) > 15: continue
        kind = 'big' if h > 22 and w > 22 else 'v' if h > 1.5*w else 'h' if w > 1.5*h else 'd'
        out.append(((sl[1].start+sl[1].stop)/6, (sl[0].start+sl[0].stop)/6, round(w), round(h), kind))
    return sorted(out)

def parse(path):
    b = blobs(path); out = ''; i = 0
    while i < len(b) and len(out) < 16:
        x, y, w, h, k = b[i]; n = b[i+1] if i+1 < len(b) else None
        same = n is not None and abs(n[0]-x) < 7
        if k == 'big': out += '0'; i += 1
        elif k == 'v' and n and n[4] == 'v' and n[0]-x < 22: out += '4'; i += 2
        elif k == 'v' and n and n[4] == 'd' and n[0]-x < 22: out += 'L'; i += 2
        elif k == 'd' and same and n[4] == 'd': out += '2'; i += 2
        elif k in 'dh' and n and n[4] in 'dh' and n[4] != k and abs(n[0]-x) < 14: out += 'J'; i += 2
        else: out += '?'; i += 1
    return out

if __name__ == '__main__':
    if len(sys.argv) > 1:
        for b in blobs(sys.argv[1]): print(b)
        print(parse(sys.argv[1]))
    else:
        prev = None
        for f in sorted(glob.glob('frames/f*.png')):
            p = parse(f)
            if p != prev: print(f[-8:-4], p)
            prev = p
