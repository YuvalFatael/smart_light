# USAGE
# python motion_detector.py
# python motion_detector.py --video videos/example_01.mp4

# import the necessary packages
import argparse
import cv2
import numpy as np
import time
import kcftracker
#import ip_configuration as IP
from picamera.array import PiRGBArray
import light
import multiprocessing as mp
import threading
from picamera import PiCamera
from configparser import ConfigParser


#Globals
config_filename = 'config.ini'
config_parser = None
do_resize = None



def get_config():
	global config_parser, do_resize, device_id
	config_parser = ConfigParser()
	config_parser.read(config_filename)
        do_resize = config_parser.getboolean('tracker', 'resized')
        device_id = config_parser.get('light', 'device_id')

def overlap(box1, box2):

    P1x = box1[0]; P1y = box1[1]; P2x = box1[0]+box1[2]; P2y = box1[1]+box1[3]
    P3x = box2[0]; P3y = box2[1]; P4x = box2[0]+box2[2]; P4y = box2[1]+box2[3]

    if not ((P2y < P3y) | (P1y > P4y) | (P2x < P3x) | (P1x > P4x)):
        return True
    return False


def isNewObject(boundingbox, trackers):
    # checks if an object, represented by bounding box, is already exists,
    # by checking the overlap of it with all other tracked objects.

    # for each tracker, check if it overlaps with the bounding box received as input
    for t in trackers:
        bbox = t.getPos()
        if do_resize:
            bbox = [bbox[0]*2, bbox[1]*2, bbox[2]*2, bbox[3]*2]
        if overlap(map(int,bbox), map(int,boundingbox)):
            return False
    # if no tracker overlap with it, return True.
    return True


def isEdge(boundingbox, frameSize):
    x = boundingbox[0]; y = boundingbox[1]; w = boundingbox[2]; h = boundingbox[3]
    rows = frameSize[0]; cols = frameSize[1];
    margins_decision = config_parser.getint('detection', 'margins_ignorance_decision')
    if x <= margins_decision+1:
        return 'Left'
    if (x+w) >= (cols-margins_decision+1):
        return 'Right'
    # if (y <= 1) | ((y+h) >= (rows-1)):
    #    return 'Vertical'

    return None



def cropRoi(image, roi):
    rows = image.shape[0]; cols = image.shape[1];
    x = roi[0]; y = roi[1]; w = roi[2]; h = roi[3]
    to_x = min(x+w+50, cols-1)
    to_y = min(y+h+50, rows-1)
    x = max(0,x-50)
    y = max(0,y-50)
    return image[y:to_y,x:to_x]


def worker(arg):
    obj, frame = arg
    return obj.update(frame)



def md(path_to_video):

    get_config()
    IMSHOW = config_parser.getboolean('debug', 'imshow')
    
    ################################################################################################################
    ### 0) Initializtion
    ################################################################################################################

    alpha = config_parser.get('detection', 'alpha_blending')
    trackers = []
    model = None
    hh = config_parser.getint('detection', 'closing_kernel_height')
    ww = config_parser.getint('detection', 'closing_kernel_width')
    sub_sampling = config_parser.getint('motion', 'sub_sampling')
    kernel = np.ones((ww,hh), np.uint8)
    flagRight = flagLeft = False
    max_time = -1
    

    cv2.namedWindow("Image")
    
    # if the video argument is None, then we are reading from webcam
    if path_to_video is None:
        camera = cv2.VideoCapture(0)
    #    camera = PiCamera()
    #    camera.resolution = (640, 480)
    #    camera.framerate = 32
    #    rawCapture = PiRGBArray(camera, size=(640, 480))
        time.sleep(0.25)

    # otherwise, we are reading from a video file
    else:
        camera = cv2.VideoCapture(path_to_video)

    # loop over the frames of the video
  #  for frame_raw in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
    while True:
        start_time = time.time()

        ################################################################################################################
        ### 1) Grab a frame
        ################################################################################################################

        # grab the current frame

        for repeat in range (1,sub_sampling-1):
            camera.read()

        (grabbed, frame) = camera.read()
        # if the frame could not be grabbed, then we have reached the end of the video
        if not grabbed:
            break

       # frame = frame_raw.array

        ################################################################################################################
        ### 2) Pre-Processing
        ################################################################################################################
        pre_start_time = time.time()
        # resize the frame, convert it to grayscale, and blur it
        
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if do_resize:
            frame_resized = cv2.resize(gray_frame, None, fx=0.5, fy=0.5, interpolation  = cv2.INTER_LINEAR)
        
        gw = config_parser.getint('detection', 'gaussian_width')
        gray = cv2.GaussianBlur(gray_frame, (gw,gw) , 0)
        frame2show = frame.copy()
        # if the first frame is None, initialize it
        if model is None:
            model = gray
            continue
        pre_end_time = time.time()
        pre_time = pre_end_time - pre_start_time
        ################################################################################################################
        ### 3) Track existing trackers, and update them
        ################################################################################################################
        flagLeft = False
        flagRight = False
        right_roi = None
        left_roi = None

        trk_start_time = time.time()
        
        #Trackers_bboxes = map(lambda x: x.update(gray_frame), trackers)
        threads = []
        if do_resize:
            tracker_frame = frame_resized
        else:
            tracker_frame = gray_frame
            
        for t in trackers:
            thread = threading.Thread(target=t.update, args=([tracker_frame]))
            threads.append(thread)
            thread.start()

        for t in threads:
            t.join()

        
            
        trk_end_time = time.time()
        trk_time = trk_end_time - trk_start_time
        
        #for t in trackers:
        #    boundingbox = t.update(gray_frame)
            #boundingbox = map(int, boundingbox)

            # if t.isTrackingBad() is True:
            #     trackers.remove(t)

       


            ############################################################################################################
            ### 4) Check for trackers that cross image boundries
            ############################################################################################################

            # if a tracker got into the frame edges, remove it.
            # in addition, raise a movement flag about the relevant direction (left or right)
        for t in trackers:

            if t.isNotMoving():
                trackers.remove(t)
                continue
            
            boundingbox = t.getPos()
            if do_resize:
                boundingbox = [boundingbox[0]*2, boundingbox[1]*2, boundingbox[2]*2, boundingbox[3]*2]
            edge = isEdge(boundingbox, [gray_frame.shape[0], gray_frame.shape[1]])
            if edge is not None:
                if edge is 'Right':
                    flagRight = True
                    right_roi = boundingbox
                if edge is 'Left':
                    flagLeft = True
                    left_roi = boundingbox
                speed = t.getVelocity() #in pixels per frame!!
                
                delta_alpha = speed / config_parser.getint('motion', 'image_width') * config_parser.getfloat('motion', 'camera_fov')
                speedMetersPerFrame = 2 * config_parser.getfloat('motion', 'camera_distance') * np.tan(np.radians(2*delta_alpha))
                speedMeterPerSecond = speedMetersPerFrame * config_parser.getfloat('motion', 'frames_per_sec')
                                                                                          
               # print "speed is : {}".format(speed)
                                                                                          
                trackers.remove(t)
                

            if IMSHOW:
                cv2.rectangle(frame2show, (boundingbox[0], boundingbox[1]),
                         (boundingbox[0] + boundingbox[2], boundingbox[1] + boundingbox[3]), (0, 255, 255), 2)

            # TODO: if object is not moving much, remove it.



        ################################################################################################################
        ### 5) Motion Detection assignment
        ################################################################################################################
        md_start_time = time.time()

        # compute the absolute difference between the current frame and first frame
        frameDelta = cv2.absdiff(model, gray)
        th = config_parser.getint('detection', 'absdiff_threshold')
        thresh1 = cv2.threshold(frameDelta, th, 255, cv2.THRESH_BINARY)[1]
        thresh2 = cv2.morphologyEx(thresh1, cv2.MORPH_CLOSE, kernel, 2)
        (_, cnts, _) = cv2.findContours(thresh2.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # loop over the contours
        for c in cnts:
            
            # if the contour is too small, ignore it
            if cv2.contourArea(c) < config_parser.getint('detection', 'min_blob_area'):             
                continue

            # compute the bounding box for the contour, draw it on the frame,
            # and update the text
            (x, y, w, h) = cv2.boundingRect(c)
            margins_detection = config_parser.getint('detection', 'margins_ignorance_detection')
            if x < margins_detection or (x+w) > (frame.shape[1]-margins_detection):
                continue
            aspect_ratio = float(h)/w
            if aspect_ratio < config_parser.getfloat('detection', 'person_aspect_ratio') :
                continue
            if IMSHOW:
                cv2.rectangle(frame2show, (x, y), (x + w, y + h), (0, 255, 0), 2)

            #if a new object detect, start tracking on it
            if isNewObject([x,y,w,h], trackers):
                new_tracker = kcftracker.KCFTracker(False, False, False)
                if do_resize:
                    new_tracker.init(map(int,[x/2, y/2, w/2, h/2]), frame_resized)
                else:
                    new_tracker.init([x, y, w, h], frame)
                trackers.append(new_tracker)
                trackerInit = True
                


        # TODO: if certain tracker doesn't overlap with any other detection, at least 10 frames, erase it.



        #model = cv2.addWeighted(model, 1 - alpha, gray, alpha, 0)
        md_end_time = time.time()
        md_time = md_end_time - md_start_time
        ################################################################################################################
        ### 6) Display
        ################################################################################################################
        SAVE_EVENTS = config_parser.get('motion', 'save_events')

        if flagLeft or flagRight:
            
            if IMSHOW:
                cv2.putText(frame2show, "Motion Right, speed: {:.3f} m/sec".format(speedMeterPerSecond), (10, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            if flagLeft:
                image_filename = time.strftime("%Y%m%d-%H%M%S") + '-left.jpg'
                light.motion_detected('Left', image_filename, speedMeterPerSecond)

            if flagRight:
                image_filename = time.strftime("%Y%m%d-%H%M%S") + '-right.jpg'
                light.motion_detected('Right', image_filename, speedMeterPerSecond)
                
            if SAVE_EVENTS:
                    cv2.imwrite(image_filename, frame2show)
        

        


        
        algo_end_time = time.time()
        algo_time = algo_end_time - start_time

        time_to_wait = 166 - int(algo_time*1000)
        if time_to_wait <= 0:
            time_to_wait = 1
        #print time_to_wait
        
        # show the frame and record if the user presses a key
        if IMSHOW:
            cv2.putText(frame2show, "ID: {} ".format(device_id), (5, 15),cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
            cv2.imshow("Image", frame2show)
        if config_parser.getboolean('debug', 'debug') :
            cv2.imshow("Thresh", thresh1)
            cv2.imshow("Blobs", thresh2)
            cv2.imshow("Frame Delta", frameDelta)
            cv2.imshow("Model", model)
            cv2.imshow("Gray", gray)


        key = cv2.waitKey(time_to_wait) & 0xFF
        
        # if the `q` key is pressed, break from the lop
        if key == ord("q"):
            break

        debug_end_time = time.time()
        debug_time = debug_end_time - start_time

        if config_parser.getboolean('debug', 'print_time') :
            print("--- total: {:.4f}: algo({:.4f}), pre({:.3f}), md({:.3f}), trk({:.3f})".format(debug_time, algo_time, pre_time, md_time, trk_time))
            
        #rawCapture.truncate(0)
            
    # cleanup the camera and close any open windows
    camera.release()
    cv2.destroyAllWindows()

    

if __name__ == '__main__':
        ap = argparse.ArgumentParser()
        ap.add_argument("-v", "--video", help="path to the video file", nargs=1)
        args = ap.parse_args()
	md(args.video[0])
