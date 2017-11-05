import argparse
from picamera.array import PiRGBArray
from picamera import PiCamera
import time
import cv2
import time


def record(path_to_video, timer):
    
    # find the webcam
    camera = PiCamera()
    camera.resolution = (320, 240)
    camera.framerate = 32
    rawCapture = PiRGBArray(camera, size=(320, 240))
    time.sleep(0.25)

    # video recorder
    video_writer = cv2.VideoWriter(path_to_video, cv2.VideoWriter_fourcc(*"XVID"), 30 ,(320,240))
    
    print video_writer
    # record video
    start_time = time.time()
    for frame_raw in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):

        frame = frame_raw.array
        video_writer.write(frame)

        
        cv2.imshow('Video Stream', frame)
        
        rawCapture.truncate(0)

        key = cv2.waitKey(1) & 0xFF
        # if the `q` key is pressed, break from the lop
        #if key == ord("q"):
        #    break
        
        now = int(time.time() - start_time)
        if now > int(timer):
            break

    print "finished"
    
    video_writer.release()
    #camera.release() 
    cv2.destroyAllWindows()

    
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--path", help="path to output video file", nargs=1)
    ap.add_argument("-t", "--timer", help="timer", nargs=1) 
    args = ap.parse_args()
    record(args.path[0], args.timer[0])

    
