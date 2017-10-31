# USAGE
# python motion_detector.py
# python motion_detector.py --video videos/example_01.mp4

# import the necessary packages
import argparse
import cv2
import numpy as np
import time
import kcftracker
import ip_configuration as IP
from picamera.array import PiRGBArray
import light
##############################################
# Settings
DEBUG = False
IMSHOW = False#True
SAVE_EVENTS = True#False#True
SAVE_FULL_FRAME = True
##############################################
from picamera import PiCamera

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
        if overlap(map(int,bbox), map(int,boundingbox)):
            return False
    # if no tracker overlap with it, return True.
    return True


def isEdge(boundingbox, frameSize):
    x = boundingbox[0]; y = boundingbox[1]; w = boundingbox[2]; h = boundingbox[3]
    rows = frameSize[0]; cols = frameSize[1];

    if x <= IP.MARGINS_IGNORANCE_TO_DECISION+1:
        return 'Left'
    if (x+w) >= (cols-IP.MARGINS_IGNORANCE_TO_DECISION+1):
        return 'Right'
    if (y <= 1) | ((y+h) >= (rows-1)):
        return 'Vertical'

    return None


def cropRoi(image, roi):
    rows = image.shape[0]; cols = image.shape[1];
    x = roi[0]; y = roi[1]; w = roi[2]; h = roi[3]
    to_x = min(x+w+50, cols-1)
    to_y = min(y+h+50, rows-1)
    x = max(0,x-50)
    y = max(0,y-50)
    return image[y:to_y,x:to_x]


def md(path_to_video):
    ################################################################################################################
    ### 0) Initializtion
    ################################################################################################################

    # construct the argument parser and parse the arguments


    alpha = IP.ALPHA_BLENDING
    trackers = []
    model = None
    kernel = np.ones(IP.CLOSING_KERNEL, np.uint8)
    flagRight = flagLeft = False

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
        (grabbed, frame) = camera.read()
        # if the frame could not be grabbed, then we have reached the end of the video
        if not grabbed:
            break

       # frame = frame_raw.array

        ################################################################################################################
        ### 2) Pre-Processing
        ################################################################################################################

        # resize the frame, convert it to grayscale, and blur it
        if frame.shape[0] > 240 or frame.shape[1] > 360:
            frame = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation  = cv2.INTER_LINEAR)
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray_frame, (21, 21), 0)
        frame2show = frame.copy()
        # if the first frame is None, initialize it
        if model is None:
            model = gray
            continue

        ################################################################################################################
        ### 3) Track existing trackers, and update them
        ################################################################################################################
        flagLeft = False
        flagRight = False
        right_roi = None
        left_roi = None
        for t in trackers:
            boundingbox = t.update(gray_frame)
            boundingbox = map(int, boundingbox)

            # if t.isTrackingBad() is True:
            #     trackers.remove(t)



            ############################################################################################################
            ### 4) Check for trackers that cross image boundries
            ############################################################################################################

            # if a tracker got into the frame edges, remove it.
            # in addition, raise a movement flag about the relevant direction (left or right)

            edge = isEdge(boundingbox, [gray_frame.shape[0], gray_frame.shape[1]])
            if edge is not None:
                if edge is 'Right':
                    flagRight = True
                    right_roi = boundingbox
                if edge is 'Left':
                    flagLeft = True
                    left_roi = boundingbox
                trackers.remove(t)


            cv2.rectangle(frame2show, (boundingbox[0], boundingbox[1]),
                     (boundingbox[0] + boundingbox[2], boundingbox[1] + boundingbox[3]), (0, 255, 255), 2)

            # TODO: if object is not moving much, remove it.



        ################################################################################################################
        ### 5) Motion Detection assignment
        ################################################################################################################

        # compute the absolute difference between the current frame and first frame
        frameDelta = cv2.absdiff(model, gray)
        thresh1 = cv2.threshold(frameDelta,IP.ABSDIFF_THRESHOLD, 255, cv2.THRESH_BINARY)[1]
        thresh2 = cv2.morphologyEx(thresh1, cv2.MORPH_CLOSE, kernel, 2)
        (_, cnts, _) = cv2.findContours(thresh2.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # loop over the contours
        for c in cnts:
            # if the contour is too small, ignore it
            if cv2.contourArea(c) < IP.MIN_BLOB_AREA:
                continue

            # compute the bounding box for the contour, draw it on the frame,
            # and update the text
            (x, y, w, h) = cv2.boundingRect(c)
            if x < IP.MARGINS_IGNORANCE_TO_DETECT or (x+w) > (frame.shape[1]-IP.MARGINS_IGNORANCE_TO_DETECT):
                continue
            aspect_ratio = float(h)/w
            if aspect_ratio < IP.PERSON_ASPECT_RATIO:
                continue
            cv2.rectangle(frame2show, (x, y), (x + w, y + h), (0, 255, 0), 2)

            #if a new object detect, start tracking on it
            if isNewObject([x,y,w,h], trackers):
                new_tracker = kcftracker.KCFTracker(False, False, False)
                new_tracker.init([x, y, w, h], frame)
                trackers.append(new_tracker)
                trackerInit = True


        # TODO: if certain tracker doesn't overlap with any other detection, at least 10 frames, erase it.



        model = cv2.addWeighted(model, 1 - alpha, gray, alpha, 0)

        ################################################################################################################
        ### 6) Display
        ################################################################################################################
        if flagLeft:
            cv2.putText(frame2show, "Motion Left", (10, 20),cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            # TODO: send message to left neighbours
            if SAVE_EVENTS:
                if not SAVE_FULL_FRAME:
                    # Crop image
                    imCrop = cropRoi(frame2show, left_roi)
                else:
                    imCrop = frame2show
                image_fliename = time.strftime("%Y%m%d-%H%M%S") + '-left.jpg'
                cv2.imwrite(image_fliename, imCrop)
                light.motion_detected('Left', image_fliename)
        if flagRight:
            cv2.putText(frame2show, "Motion Right", (10, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            # TODO: send message to right neighbour
            if SAVE_EVENTS:
                if not SAVE_FULL_FRAME:
                    # Crop image
                    imCrop = cropRoi(frame2show, right_roi)
                else:
                    imCrop = frame2show
                image_fliename = time.strftime("%Y%m%d-%H%M%S") + '-right.jpg'
                cv2.imwrite(image_fliename, imCrop)
                light.motion_detected('Right', image_fliename)

        #print("--- %s seconds ---" % (time.time() - start_time))



        # show the frame and record if the user presses a key
        if IMSHOW:
            cv2.imshow("Image", frame2show)
        if DEBUG:
            cv2.imshow("Thresh", thresh1)
            cv2.imshow("Blobs", thresh2)
            cv2.imshow("Frame Delta", frameDelta)
            cv2.imshow("Model", model)
            cv2.imshow("Gray", gray)
        key = cv2.waitKey(1) & 0xFF


  #      rawCapture.truncate(0)

        # if the `q` key is pressed, break from the lop
        if key == ord("q"):
            break

    # cleanup the camera and close any open windows
    camera.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
        ap = argparse.ArgumentParser()
        ap.add_argument("-v", "--video", help="path to the video file", nargs=1)
        args = ap.parse_args()
	md(args.video[0])
