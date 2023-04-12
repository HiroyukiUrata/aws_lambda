import boto3
import os
import sys
import uuid
from urllib.parse import unquote_plus
from PIL import Image
import PIL.Image
import PIL.ExifTags as ExifTags
import json
import re
import traceback
import psycopg2
import psycopg2.extras
import math

s3cli = boto3.client('s3')

def resize_image(image_path, resized_path):
    with Image.open(image_path) as image:
        image.thumbnail(tuple(n / 2 for n in image.size))
        image.save(resized_path)

#Exif解析クラス
class ExifImage:
    
    def __init__(self, fname):
        # 画像ファイルを開く --- (*1)
        self.img = Image.open(fname)
        self.exif = {}
        if self.img._getexif():
            for k, v in self.img._getexif().items():
                if k in ExifTags.TAGS:
                    self.exif[ExifTags.TAGS[k]] = v
 
    def print(self):
        if self.exif:
            for k, v in self.exif.items():
                print(k, ":", v)
        else:
            print("exif情報は記録されていません。")

    def __conv_deg(self, v):
        # 分数を度に変換
        d,m,s=[0,0,0]
        if type(v[0]) is tuple:
            d = float(v[0][0])/float(v[0][1])
        else:
            d = float(v[0])
             
        if type(v[1]) is tuple:
            m = float(v[1][0])/float(v[1][1])
        else:
            m = float(v[1])
             
        if type(v[2]) is tuple:
            s = float(v[2][0])/float(v[2][1])
        else:
          s = float(v[2])
 
        return d + (m / 60.0) + (s / 3600.0)

    def get_gps(self):
        datetime = None        
        if "DateTimeOriginal" in self.exif:
            datetime = re.sub(r'(\d{4}):(\d{2}):(\d{2})', r'\1/\2/\3', self.exif["DateTimeOriginal"])
 
        if "GPSInfo" in self.exif:
            gps_tags = self.exif["GPSInfo"]
        else:
            gps_tags = {}
        gps = {}
        if gps_tags:
            for t in gps_tags:
                gps[ExifTags.GPSTAGS.get(t, t)] = gps_tags[t]
                #print("{0} :{1}",ExifTags.GPSTAGS.get(t, t),gps_tags[t])
                
            #print(gps["GPSLatitude"])
            latitude = self.__conv_deg(gps["GPSLatitude"])
            lat_ref = gps["GPSLatitudeRef"]
            if lat_ref != "N":
                latitude = 0 - latitude
            longitude = self.__conv_deg(gps["GPSLongitude"])
            lon_ref = gps["GPSLongitudeRef"]
            if lon_ref != "E":
                longitude = 0 - longitude
            
            direction = None #真方位(真北を基準にして測った方位）を返す
            if "GPSImgDirection" in gps:
                try: 
                    #print(gps["GPSImgDirection"])                  
                    if type(gps["GPSImgDirection"]) is tuple:
                        if float(gps["GPSImgDirection"][1])!=0:
                            direction = float(gps["GPSImgDirection"][0])/float(gps["GPSImgDirection"][1])
                            dir_ref = gps["GPSLatitudeRef"]
                            if dir_ref != "M":
                                direction = direction - 7     
                    elif not math.isnan(gps["GPSImgDirection"]):
                        #真方位に6.75度⇒7度プラスすれば磁針方位になる
                        direction = float(gps["GPSImgDirection"])
                        dir_ref = gps["GPSLatitudeRef"]
                        if dir_ref != "M":
                            direction = direction - 7
                except Exception as e:
                    pass
                    print(traceback.format_exc())
                finally:
                    pass
                    
                 
                
            return [latitude,longitude,direction,datetime]
 
        else:
            return None#"経度・緯度は記録されていません。"  

#注意：1個ずつアップロードにしか対応してない。まとめてアップロードに対応すること！！
def lambda_handler(event, context):
    for record in event['Records']:	
        bucket = record['s3']['bucket']['name']
        key = unquote_plus(record['s3']['object']['key'])
        splitkey = key.split('/')
        newkey = key.replace(splitkey[0], 'thumbnails')
        tmpkey = key.replace('/', '')	
        download_path = '/tmp/{}{}'.format(uuid.uuid4(), tmpkey)
        upload_path = '/tmp/resized-{}'.format(tmpkey)
        s3cli.download_file(bucket, key, download_path)
        

        a = ExifImage(download_path)
        b = a.get_gps()
        if b:
            pass
            latitude,longitude,direction,datetime = b
 

            #サイズの縮小
            imagedata = Image.open(download_path)
            width, height = imagedata.size
            width2 = width/10
            height2 = height/10
            imagedata2= imagedata.resize((int(width2),int(height2)))
            #newimage = os.path.join(dname, os.path.basename(file))
            imagedata2.save(upload_path, quality=85,optimize=True)

            #pic= imagedata.resize((int(width2),int(height2)))
            pic = open(upload_path, 'rb').read()

            #pic = open(os.path.join(dname, os.path.basename(file)), 'rb').read()
            # sql = "INSERT INTO public.sample(geom,direction,filename,byteaimage,timestamp) VALUES (ST_GeomFromText('POINT({0:.06f} {1:.06f})',4326),{2},'{3}',{4},'{5}');"\
            # .format(longitude,latitude,'Null' if direction is None else direction,os.path.basename(key),psycopg2.Binary(pic),datetime)
            
            #データベースに登録
            
            sql = "INSERT INTO public.sample(geom,direction,filename,byteaimage,timestamp) VALUES (ST_GeomFromText('POINT({0:.06f} {1:.06f})',4326),{2},'{3}',{4},'{5}');"\
            .format(longitude,latitude,'Null' if direction is None else direction,os.path.basename(key),psycopg2.Binary(pic),datetime)
            
            connect = psycopg2.connect(
                database=os.environ['SAMPLE_DB'],
                user=os.environ['SAMPLE_USER'],
                password=os.environ['SAMPLE_PASS'],
                host=os.environ['SAMPLE_HOST'],
                port=os.environ['SAMPLE_PORT'],
            )
            cursor = connect.cursor()
            
            try:
                pass
                cursor.execute(sql)
            
                cursor.execute('SELECT COUNT(*) FROM public.sample')
                result = cursor.fetchone()

                
            except psycopg2.Error as e:
                print("SQL error: " + sql + "/n")
                
            cursor.close()
            connect.commit()
            connect.close()
        return {
            'statuscode': 200,
            'body': result,
        }
        
        #resize_image(download_path, upload_path)
        #s3cli.upload_file(upload_path, bucket, newkey)