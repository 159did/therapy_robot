#!/usr/bin/env python3
import argparse,json
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont

ACUPOINTS=[('大椎',.50,.04),('肺俞-L',.42,.20),('肺俞-R',.58,.20),('心俞-L',.42,.32),('心俞-R',.58,.32),('肾俞-L',.40,.68),('肾俞-R',.60,.68)]
TEMPLATE_LEVELS=[('neck',0.00,.16),('shoulder',.12,.72),('mid_back',.35,.58),('waist',.68,.42),('bottom',1.00,.50)]
TEMPLATE_ACUPOINTS=[('大椎',0.00,.04),('肺俞-L',-.22,.20),('肺俞-R',.22,.20),('心俞-L',-.22,.32),('心俞-R',.22,.32),('肾俞-L',-.26,.68),('肾俞-R',.26,.68)]
STANDARD_TEMPLATE_PATH='/home/zzq/PTR/therapy_robot/back/standard_back_template.json'
FONT_CANDIDATES=['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','/usr/share/fonts/truetype/arphic/uming.ttc','/usr/share/fonts/truetype/arphic/ukai.ttc']

def get_font(size=16):
    for p in FONT_CANDIDATES:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def put_text_cn(img,text,xy,color=(255,255,255),size=16):
    rgb=cv2.cvtColor(img,cv2.COLOR_BGR2RGB); pil=Image.fromarray(rgb); draw=ImageDraw.Draw(pil); draw.text(tuple(map(int,xy)),str(text),font=get_font(size),fill=(int(color[2]),int(color[1]),int(color[0])))
    return cv2.cvtColor(np.asarray(pil),cv2.COLOR_RGB2BGR)

def smooth(a,k=19):
    a=np.asarray(a,float)
    if len(a)<3:return a
    k=min(k,len(a)//2*2+1)
    return cv2.GaussianBlur(a.reshape(-1,1),(1,k),0).ravel()

def limit_step(a,step=2.0):
    o=np.asarray(a,float).copy()
    for rng in (range(1,len(o)),range(len(o)-2,-1,-1)):
        for i in rng:
            j=i-1 if rng.start==1 else i+1; d=o[i]-o[j]
            if abs(d)>step:o[i]=o[j]+np.sign(d)*step
    return o

def depth_mask(z,center_roi=80,near_margin=.10,far_margin=.10):
    h,w=z.shape; q=center_roi//2; r=z[max(0,h//2-q):min(h,h//2+q),max(0,w//2-q):min(w,w//2+q)]; vals=r[r>0]; allv=z[z>0]
    c=float(np.median(vals)) if vals.size else float(np.percentile(allv,10)); near=max(.05,c-near_margin); far=c+far_margin
    m=((z>=near)&(z<=far)).astype(np.uint8)*255; k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9))
    m=cv2.morphologyEx(m,cv2.MORPH_CLOSE,k,iterations=2); m=cv2.morphologyEx(m,cv2.MORPH_OPEN,k,iterations=1)
    return m,c,near,far

def largest_center_component(mask):
    n,lab,st,_=cv2.connectedComponentsWithStats(mask,8); h,w=mask.shape; cx=w//2; best=0; score=-1e18
    for i in range(1,n):
        x,y,ww,hh,area=st[i]; s=area*(3 if x<=cx<x+ww else 1)-abs(x+ww/2-cx)*50
        if s>score:best=i; score=s
    return ((lab==best).astype(np.uint8)*255) if best else mask

def central_body_mask(mask):
    k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(31,31)); core=cv2.erode(mask,k,iterations=1); core=largest_center_component(core); core=cv2.dilate(core,k,iterations=1)
    return cv2.bitwise_and(mask,core)

def row_segments(row):
    xs=np.flatnonzero(row>0)
    if xs.size==0:return []
    g=np.where(np.diff(xs)>1)[0]; s=np.r_[0,g+1]; e=np.r_[g,xs.size-1]
    return [(int(xs[a]),int(xs[b])) for a,b in zip(s,e)]

def middle_segment_profile(mask):
    h,w=mask.shape; ic=w/2; c0=np.full(h,np.nan)
    for y in range(h):
        segs=row_segments(mask[y])
        if segs:
            a,b=min(segs,key=lambda s:abs((s[0]+s[1])*.5-ic)-.04*(s[1]-s[0]+1)); c0[y]=(a+b)*.5
    v=np.isfinite(c0)
    if v.sum()<20:raise RuntimeError('not enough body rows')
    cref=smooth(np.interp(np.arange(h),np.flatnonzero(v),c0[v]),31); rows=[]
    for y in range(h):
        segs=row_segments(mask[y])
        if not segs:continue
        a,b=min(segs,key=lambda s:abs((s[0]+s[1])*.5-cref[y])-.05*(s[1]-s[0]+1)); ww=b-a+1
        if ww>=20:rows.append((y,a,b,ww,(a+b)*.5))
    return rows

def estimate_back(rows,h=None):
    ys=np.array([r[0] for r in rows]); left=smooth([r[1] for r in rows],25); right=smooth([r[2] for r in rows],25); center=smooth([r[4] for r in rows],25); width=smooth(right-left,25)
    maxw=float(width.max()); good=width>max(45,maxw*.30); gy=ys[good]; top=int(gy[0]); bottom=int(gy[-1]); span=max(1,bottom-top)
    up=(ys>=top)&(ys<=top+int(span*.30))&good
    neck=top if not up.any() else int(ys[up][np.argmin(width[up])]); back_top=min(bottom-20,neck+max(4,int(span*.015))); idx=np.where((ys>=back_top)&(ys<=bottom)&good)[0]
    p={'ys':ys,'left':left,'right':right,'center':center,'width':width,'top':top,'bottom':bottom,'neck_y':neck,'back_top':back_top,'idx':idx,'rgb_boundary_confidence':0.0}
    return apply_shoulder_waist_model(fit_model(p))

def fit_model(p):
    ys=p['ys']; idx=p['idx']; y=ys[idx].astype(float); yn=(y-y.min())/max(1,y.max()-y.min())
    cp=np.polyfit(yn,p['center'][idx],2,w=np.maximum(30,p['width'][idx])); wp=np.polyfit(yn,p['width'][idx],2,w=np.sqrt(np.maximum(30,p['width'][idx]))); ya=(ys-y.min())/max(1,y.max()-y.min())
    b=np.zeros_like(ys,dtype=float); b[idx]=.68; b=np.interp(ys,ys[idx],b[idx],left=0,right=0)
    p['center']=smooth(limit_step((1-b)*p['center']+b*np.polyval(cp,ya),2),15); p['width']=(1-b)*p['width']+b*np.maximum(55,np.polyval(wp,ya)); p['left']=p['center']-p['width']/2; p['right']=p['center']+p['width']/2; p['centerline_poly']=[float(x) for x in cp]; p['width_poly']=[float(x) for x in wp]
    return p

def apply_shoulder_waist_model(p):
    ys=p['ys']; idx=p['idx']; top=p['back_top']; bot=p['bottom']; span=max(1,bot-top); up=idx[(ys[idx]>=top)&(ys[idx]<=top+int(span*.38))]; low=idx[(ys[idx]>=top+int(span*.45))&(ys[idx]<=top+int(span*.85))]
    if len(up)<5 or len(low)<5:return p
    si=up[int(np.argmax(smooth(np.gradient(smooth(p['width'][up],11)),9)))]; wi=low[int(np.argmin(p['width'][low]))]; sy=int(ys[si]); wy=int(ys[wi])
    if wy<=sy+20:return p
    sl,sr,wl,wr=map(float,(p['left'][si],p['right'][si],p['left'][wi],p['right'][wi])); ww=float(p['width'][wi]); l=p['left'].copy(); r=p['right'].copy(); ch=[]
    for i,y in enumerate(ys):
        if y<sy:continue
        if y<=wy:
            t=(y-sy)/max(1,wy-sy); nl=max(l[i],sl+(wl-sl)*t); nr=min(r[i],sr+(wr-sr)*t)
        else:
            mw=max(70,ww*1.08); nl=max(l[i],p['center'][i]-mw/2); nr=min(r[i],p['center'][i]+mw/2)
        if nr-nl>=55:ch.append(max(0,(r[i]-l[i])-(nr-nl))); l[i],r[i]=nl,nr
    p['left']=smooth(l,17); p['right']=smooth(r,17); p['center']=(p['left']+p['right'])/2; p['width']=p['right']-p['left']; p['shoulder_y']=sy; p['waist_narrow_y']=wy; p['shoulder_points']=[[sl,float(sy)],[sr,float(sy)]]; p['waist_points']=[[wl,float(wy)],[wr,float(wy)]]; p['shoulder_waist_suppression_mean_px']=float(np.mean(ch)) if ch else 0.0
    return p

def refine_profile_with_rgb(rgb,profile):
    gray=cv2.cvtColor(rgb,cv2.COLOR_BGR2GRAY); luma=cv2.GaussianBlur(gray,(0,0),2.0).astype(np.float32)
    gx=cv2.Sobel(luma,cv2.CV_32F,1,0,ksize=3); gy=cv2.Sobel(luma,cv2.CV_32F,0,1,ksize=3)
    edge=cv2.magnitude(gx,gy); dark=np.maximum(0,cv2.GaussianBlur(luma,(0,0),13)-luma); score=.65*edge+.35*dark
    left=profile['left'].copy(); right=profile['right'].copy(); conf=[]
    h,w=gray.shape
    for i,y in enumerate(profile['ys']):
        if y<profile['back_top'] or y>profile['bottom']:continue
        yy=int(np.clip(y,0,h-1)); cur_l=int(round(left[i])); cur_r=int(round(right[i]));
        lx0,lx1=max(0,cur_l-24),min(w-1,cur_l+16); rx0,rx1=max(0,cur_r-16),min(w-1,cur_r+24)
        if lx1>lx0:
            xs=np.arange(lx0,lx1+1); vals=score[yy,lx0:lx1+1]-.08*np.abs(xs-cur_l); x=int(xs[np.argmax(vals)]); conf.append(float(score[yy,x])); left[i]=.72*left[i]+.28*x
        if rx1>rx0:
            xs=np.arange(rx0,rx1+1); vals=score[yy,rx0:rx1+1]-.08*np.abs(xs-cur_r); x=int(xs[np.argmax(vals)]); conf.append(float(score[yy,x])); right[i]=.72*right[i]+.28*x
    profile['left']=smooth(left,17); profile['right']=smooth(right,17); profile['center']=(profile['left']+profile['right'])/2; profile['width']=profile['right']-profile['left']; profile['rgb_boundary_confidence']=float(np.mean(conf)) if conf else 0.0
    return profile,score,luma

def draw_rgb_debug(rgb,score,p,out):
    if score is None: return
    s=np.uint8(np.clip(score/(np.percentile(score,99)+1e-6),0,1)*255); heat=cv2.applyColorMap(s,cv2.COLORMAP_TURBO); vis=cv2.addWeighted(rgb,.55,heat,.45,0)
    for y in p['ys'][::4]:
        y=int(y); cv2.circle(vis,(int(interp(p,y,'left')),y),1,(255,0,0),-1); cv2.circle(vis,(int(interp(p,y,'right')),y),1,(0,0,255),-1); cv2.circle(vis,(int(interp(p,y,'center')),y),1,(0,255,0),-1)
    cv2.imwrite(str(out),vis)

def interp(p,y,k):return float(np.interp(y,p['ys'],p[k]))

def arc_rows(p):
    rows=p['ys'][(p['ys']>=p['back_top'])&(p['ys']<=p['bottom'])]; c=np.array([interp(p,int(y),'center') for y in rows]); s=np.zeros(len(rows))
    if len(rows)>1:s[1:]=np.cumsum(np.sqrt(np.diff(rows.astype(float))**2+np.diff(c)**2))
    return rows,s

def y_at_v(p,v):
    rows,s=arc_rows(p)
    return int(round(np.interp(v*s[-1],s,rows))) if len(rows)>1 and s[-1]>0 else int(p['back_top']+(p['bottom']-p['back_top'])*v)

def normal_at(depth,meta,x,y,roi=80,step=4):
    ins=meta['intrinsics']; fx,fy,ppx,ppy=map(float,(ins['fx'],ins['fy'],ins['ppx'],ins['ppy'])); scale=float(meta.get('depth_scale_m_per_unit',0.0001)); h,w=depth.shape; pts=[]; q=roi//2
    for yy in range(max(0,y-q),min(h-1,y+q)+1,step):
        for xx in range(max(0,x-q),min(w-1,x+q)+1,step):
            z=float(depth[yy,xx])*scale
            if .05<=z<=1.2:pts.append([(xx-ppx)/fx*z,(yy-ppy)/fy*z,z])
    pts=np.asarray(pts,float)
    if len(pts)<20:return None
    c=pts.mean(0); a=pts-c; _,_,vh=np.linalg.svd(a,full_matrices=False); n=vh[-1]
    if n[2]<0:n=-n
    r=np.abs(a@n); return {'point_camera_m':[float(x) for x in c],'normal_camera':[float(x) for x in n],'valid':int(len(pts)),'residual_median_mm':float(np.median(r)*1000)}

def acupoints_from_profile(p,depth,meta):
    out=[]
    for name,u,v in ACUPOINTS:
        y=y_at_v(p,v); l=interp(p,y,'left'); r=interp(p,y,'right'); x=int(round(l+(r-l)*u)); n=normal_at(depth,meta,x,y); a={'name':name,'u':u,'v':v,'arc_fraction':v,'pixel':[x,y],'ok':n is not None}
        if n:a.update(n)
        out.append(a)
    return out

def load_standard_template(path=STANDARD_TEMPLATE_PATH):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    left=np.asarray(data['outline_left'],float); right=np.asarray(data['outline_right'],float)
    v=np.unique(np.r_[left[:,1],right[:,1]])
    lx=np.interp(v,left[:,1],left[:,0]); rx=np.interp(v,right[:,1],right[:,0])
    center=(lx+rx)/2; half=(rx-lx)/2
    return {'path':str(path),'name':data.get('name','standard_template'),'v':v,'left_x':lx,'right_x':rx,'center_norm':center,'half_norm':half,'acupoints':data.get('acupoints',[]),'landmarks':data.get('landmarks',{})}

def standard_half_width(tpl,v):return float(np.interp(v,tpl['v'],tpl['half_norm']))
def standard_center_offset(tpl,v):return float(np.interp(v,tpl['v'],tpl['center_norm']))

def image_y_for_template_v(p,v):
    anchors_v=[0,.12,.35,.68,1.0]; anchors_y=[p['back_top'],p.get('shoulder_y',y_at_v(p,.12)),y_at_v(p,.35),p.get('waist_narrow_y',y_at_v(p,.68)),p['bottom']]
    return int(round(np.interp(v,anchors_v,anchors_y)))

def template_acupoints_from_profile(p,depth,meta):
    tpl=load_standard_template(); anchors=[.12,.35,.68,1.0]
    obs=[]; std=[]
    for v in anchors:
        y=image_y_for_template_v(p,v); obs.append(max(55,interp(p,y,'right')-interp(p,y,'left'))/2); std.append(max(.05,standard_half_width(tpl,v)))
    scale=float(np.median(np.asarray(obs)/np.asarray(std)))
    out=[]
    for item in tpl.get('acupoints',[]):
        name,u,v=item['name'],float(item['x']),float(item['v'])
        y=image_y_for_template_v(p,v); c=interp(p,y,'center')+standard_center_offset(tpl,v)*scale; tpl_half=standard_half_width(tpl,v)*scale; obs_half=(interp(p,y,'right')-interp(p,y,'left'))/2; half=.75*tpl_half+.25*obs_half; x=int(round(c+u*half)); n=normal_at(depth,meta,x,y); a={'name':name,'template_x':u,'template_v':v,'pixel':[x,y],'ok':n is not None}
        if n:a.update(n)
        out.append(a)
    return out,scale

def template_fit_contour(p,scale=None,n=100):
    tpl=load_standard_template()
    if scale is None:
        _,scale=template_acupoints_from_profile(p,np.zeros((1,1),np.uint16),{'intrinsics':{'fx':1,'fy':1,'ppx':0,'ppy':0},'depth_scale_m_per_unit':1})
    left=[]; right=[]; center=[]
    for v in np.linspace(0,1,n):
        y=image_y_for_template_v(p,float(v)); c=interp(p,y,'center')+standard_center_offset(tpl,float(v))*scale; tpl_half=standard_half_width(tpl,float(v))*scale; obs_half=(interp(p,y,'right')-interp(p,y,'left'))/2; half=.75*tpl_half+.25*obs_half
        left.append([float(c-half),float(y)]); right.append([float(c+half),float(y)]); center.append([float(c),float(y)])
    levels={'template_path':tpl['path'],'neck':p['back_top'],'shoulder':p.get('shoulder_y',y_at_v(p,.12)),'mid_back':image_y_for_template_v(p,.35),'waist':p.get('waist_narrow_y',y_at_v(p,.68)),'bottom':p['bottom']}
    return {'left':left,'right':right,'center':center,'levels':levels,'scale':float(scale),'standard_template_name':tpl.get('name','standard_template')}

def draw_template_fit(rgb,mask,p,fit,tpl,out):
    img=rgb.copy(); img[mask>0]=(img[mask>0]*.65+np.array([0,120,255])*.35).astype(np.uint8)
    obs_l=[(int(interp(p,int(y),'left')),int(y)) for y in p['ys'][::3]]; obs_r=[(int(interp(p,int(y),'right')),int(y)) for y in p['ys'][::3]]
    if len(obs_l)>1:cv2.polylines(img,[np.asarray(obs_l,np.int32)],False,(255,0,0),2)
    if len(obs_r)>1:cv2.polylines(img,[np.asarray(obs_r,np.int32)],False,(0,0,255),2)
    fl=np.asarray([[int(x),int(y)] for x,y in fit['left']],np.int32); fr=np.asarray([[int(x),int(y)] for x,y in fit['right']],np.int32); fc=np.asarray([[int(x),int(y)] for x,y in fit['center']],np.int32)
    cv2.polylines(img,[fl],False,(0,255,0),2); cv2.polylines(img,[fr],False,(0,255,0),2); cv2.polylines(img,[fc],False,(0,255,255),2)
    for name,y in fit['levels'].items():
        if not isinstance(y,(int,float,np.integer,np.floating)):continue
        cv2.line(img,(0,int(y)),(img.shape[1]-1,int(y)),(255,255,0),1); cv2.putText(img,name,(8,int(y)-4),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,0),1)
    for a in tpl:
        cv2.circle(img,tuple(a['pixel']),7,(0,255,0),2); img=put_text_cn(img,a['name'],(a['pixel'][0]+8,a['pixel'][1]-8),(0,255,0),15)
    cv2.imwrite(str(out),img)

def draw(rgb,mask,p,obs,tpl,out):
    img=rgb.copy(); img[mask>0]=(img[mask>0]*.7+np.array([0,120,255])*.3).astype(np.uint8)
    for y in p['ys'][::5]:
        y=int(y); cv2.circle(img,(int(interp(p,y,'left')),y),1,(255,0,0),-1); cv2.circle(img,(int(interp(p,y,'right')),y),1,(0,0,255),-1); cv2.circle(img,(int(interp(p,y,'center')),y),1,(0,255,0),-1)
    for a in obs:
        cv2.circle(img,tuple(a['pixel']),10,(0,0,255),2); img=put_text_cn(img,a['name'],(a['pixel'][0]+9,a['pixel'][1]-8),(0,0,255),15)
    for a in tpl:
        cv2.circle(img,tuple(a['pixel']),7,(0,255,0),2); img=put_text_cn(img,'T-'+a['name'],(a['pixel'][0]+7,a['pixel'][1]+8),(0,255,0),14)
    cv2.imwrite(str(out),img)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('sample',nargs='?',default='/home/zzq/PTR/therapy_robot/data/d405_samples/back_20260617_212933_470'); a=ap.parse_args(); sample=Path(a.sample)
    rgb=cv2.imread(str(sample/'rgb.png')); depth=np.load(sample/'depth_z16.npy'); meta=json.loads((sample/'meta.json').read_text()); z=depth.astype(np.float32)*float(meta.get('depth_scale_m_per_unit',0.0001))
    mask,c,near,far=depth_mask(z); mask=central_body_mask(largest_center_component(mask)); prof=estimate_back(middle_segment_profile(mask),depth.shape[0]); prof,score,luma=refine_profile_with_rgb(rgb,prof); obs=acupoints_from_profile(prof,depth,meta); tpl,scale=template_acupoints_from_profile(prof,depth,meta); fit=template_fit_contour(prof,scale)
    out=sample/'analysis_back_contour.png'; out_rgb=sample/'analysis_rgb_shadow_debug.png'; out_fit=sample/'analysis_template_fit.png'; draw(rgb,mask,prof,obs,tpl,out); draw_rgb_debug(rgb,score,prof,out_rgb); draw_template_fit(rgb,mask,prof,fit,tpl,out_fit); rows,s=arc_rows(prof); res={'sample':str(sample),'depth_center_m':c,'depth_range_m':[near,far],'neck_y':prof['neck_y'],'back_top_y':prof['back_top'],'bottom_y':prof['bottom'],'shoulder_y':prof.get('shoulder_y'),'waist_narrow_y':prof.get('waist_narrow_y'),'rgb_boundary_confidence':prof.get('rgb_boundary_confidence',0.0),'spine_arc_length_px':float(s[-1]) if len(s) else 0,'template_width_scale_px':scale,'template_fit_contour':fit,'observed_acupoints':obs,'template_acupoints':tpl,'acupoints':tpl,'outputs':{'image':str(out),'rgb_shadow_debug':str(out_rgb),'template_fit':str(out_fit)}}
    (sample/'analysis_result.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'ok':True,'image':str(out),'rgb_shadow_debug':str(out_rgb),'template_fit':str(out_fit),'json':str(sample/'analysis_result.json'),'rgb_boundary_confidence':prof.get('rgb_boundary_confidence',0.0),'observed':len(obs),'template':len(tpl),'valid_template':sum(1 for x in tpl if x['ok'])},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
