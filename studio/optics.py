"""Shared frame-format calculations, independent of Qt and Blender."""
import math

ASPECTS=[('3:2',3,2),('2:3',2,3),('3:4',3,4),('4:3',4,3),('16:9',16,9),
         ('9:16',9,16),('1:1',1,1),('2.35:1',2.35,1),('2.39:1',2.39,1),
         ('1.85:1',1.85,1),('1.66:1',1.66,1)]

def validate_aspect(width,height):
    width,height=float(width),float(height)
    if not (math.isfinite(width) and math.isfinite(height) and width>0 and height>0 and .25<=width/height<=4):
        raise ValueError('比率は正の数で、幅÷高さを0.25〜4にしてください。')
    return width,height

def fit_frame(width,height,box_width,box_height):
    width,height=validate_aspect(width,height)
    scale=min(box_width/width,box_height/height)
    return max(1,round(width*scale)),max(1,round(height*scale))

def output_frame(width,height,long_edge):
    return fit_frame(width,height,long_edge,long_edge)
