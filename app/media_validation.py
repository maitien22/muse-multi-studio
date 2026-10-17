"""Strict media validation before atomic library commit."""
import json
import shutil
import struct
import subprocess
from pathlib import Path
from PIL import Image, UnidentifiedImageError


def verify_media(path, kind):
    path=Path(path)
    if not path.is_file() or path.stat().st_size<16:
        raise ValueError('Kết quả AI trống hoặc quá ngắn')
    if kind=='image':
        try:
            with Image.open(path) as im:
                if im.format not in ('JPEG','PNG','WEBP'):
                    raise ValueError('Định dạng ảnh không được hỗ trợ')
                if im.width*im.height>100_000_000:
                    raise ValueError('Ảnh vượt giới hạn số pixel')
                im.verify()
            with Image.open(path) as im:
                im.load()  # detect truncation and malformed content
            return
        except (UnidentifiedImageError,OSError) as exc:
            raise ValueError('Dữ liệu kết quả không phải ảnh hợp lệ') from exc
    if kind!='video':
        raise ValueError('Loại media không hỗ trợ')
    # At a minimum verify MP4 box structure, not merely the filename/content-type.
    with path.open('rb') as f:
        data=f.read(32)
        if len(data)<16 or data[4:8]!=b'ftyp':
            raise ValueError('Video không có MP4 file-type box hợp lệ')
        f.seek(0,2);length=f.tell();f.seek(0)
        boxes=set();pos=0
        while pos+8<=length:
            f.seek(pos);head=f.read(16)
            size=int.from_bytes(head[:4],'big');name=head[4:8]
            hdr=8
            if size==1:
                size=int.from_bytes(head[8:16],'big');hdr=16
            elif size==0:
                size=length-pos
            if size<hdr or pos+size>length:
                raise ValueError('Cấu trúc MP4 bị hỏng')
            boxes.add(name)
            pos+=size
        if pos!=length or b'mdat' not in boxes or not (b'moov' in boxes or b'moof' in boxes):
            raise ValueError('Video MP4 thiếu khung dữ liệu/metadata')
    ffprobe=shutil.which('ffprobe')
    if ffprobe:
        result=subprocess.run([ffprobe,'-v','error','-show_streams','-of','json',str(path)],
                              capture_output=True,text=True,timeout=30)
        try:
            tracks=json.loads(result.stdout).get('streams',[])
        except json.JSONDecodeError:
            tracks=[]
        if result.returncode!=0 or not any(s.get('codec_type')=='video' for s in tracks):
            raise ValueError('Không thể giải mã video kết quả')


def normalize_image(path, ratio):
    """Match displayed image aspect ratio, center crop native API output as needed."""
    from PIL import Image
    target={'9:16':(9,16),'16:9':(16,9),'1:1':(1,1),'4:3':(4,3)}[ratio]
    with Image.open(path) as image:
        w,h=image.size
        wanted=target[0]/target[1]
        if abs(w/h-wanted)<0.001:
            return
        if w/h>wanted:
            nw=max(1,round(h*wanted))
            cropped=image.crop(((w-nw)//2,0,(w-nw)//2+nw,h))
        else:
            nh=max(1,round(w/wanted))
            cropped=image.crop((0,(h-nh)//2,w,(h-nh)//2+nh))
        cropped.save(path,format=image.format,quality=95)
