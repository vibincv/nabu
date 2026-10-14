import json
import pathlib
import re
import sys
import time
import unicodedata

sys.path.insert(0, r"C:\Users\Vibin\MyWork\nabu\src")
from nabu import netguard; netguard.install()
import cv2
import numpy as np
from rapidocr import RapidOCR


def compact(s): return re.sub(r"[\W_]+","",unicodedata.normalize("NFKD",s).lower())
M=pathlib.Path(sys.argv[2]); mode=sys.argv[3]
q={"Global.log_level":"error"}
base=RapidOCR(params=q)
ko=RapidOCR(params={**q,"Rec.model_path":str(M/"korean_PP-OCRv5_rec_mobile.onnx"),"Rec.rec_keys_path":str(M/"ppocrv5_korean_dict.txt")}) if mode!="base" else None
def crop(img, quad):
    q_=np.array(quad,dtype=np.float32); w=int(max(np.linalg.norm(q_[0]-q_[1]),np.linalg.norm(q_[2]-q_[3]))); h=int(max(np.linalg.norm(q_[0]-q_[3]),np.linalg.norm(q_[1]-q_[2])))
    T=cv2.getPerspectiveTransform(q_,np.float32([[0,0],[w,0],[w,h],[0,h]])); return cv2.warpPerspective(img,T,(w,h))
def rec(e,c):
    r=e(c,use_det=False,use_cls=False,use_rec=True); return (r.txts[0],r.scores[0]) if r.txts else ("",0.0)
hangul=lambda s:any('\uac00'<=ch<='\ud7a3' for ch in s)
d=pathlib.Path(sys.argv[1])
for img_p in sorted(d.glob("*.png")):
    exp=json.loads((d/(img_p.stem+".expected.json")).read_text(encoding="utf-8"))
    img=cv2.imdecode(np.fromfile(str(img_p),dtype=np.uint8),cv2.IMREAD_COLOR)
    t=time.perf_counter()
    if mode=="base":
        r=base(img,use_det=True,use_cls=True,use_rec=True); lines=list(r.txts or [])
    else:
        det=base(img,use_det=True,use_rec=False,use_cls=False); lines=[]
        for quad in (det.boxes if det.boxes is not None else []):
            c=crop(img,quad); t1,s1=rec(base,c)
            if mode=="dual" or s1<0.8 or any('一'<=ch<='鿿' for ch in t1):
                t2,_=rec(ko,c); t1 = t2 if hangul(t2) else t1
            lines.append(t1)
    dt=time.perf_counter()-t
    ct=compact(" ".join(lines)); items=[(f["label"],f["value"]) for f in exp["fields"]]
    print(f"{img_p.stem:28s} {dt:5.1f}s labels {sum(compact(l) in ct for l,v in items)}/{len(items)} values {sum(compact(v) in ct for l,v in items)}/{len(items)}")
