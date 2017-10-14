# USAGE
# python motion_detector.py
# python motion_detector.py --video videos/example_01.mp4

# import the necessary packages
import argparse
import cv2
import numpy as np
import time
import kcftracker


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
    # if no tracker overlaped with it, return True.
    return True

def isEdge(boundingbox, frameSize):
    x = boundingbox[0]; y = boundingbox[1]; w = boundingbox[2]; h = boundingbox[3]
    rows = frameSize[0]; cols = frameSize[1];

    if x <= 1:
        return 'Left'
    if (x+w) >= (cols-1):
        return 'Right'
    if (y <= 1) | ((y+h) >= (rows-1)):
        return 'Vertical'

    return None


def main():
    ################################################################################################################
    ### 0) Initializtion
    ################################################################################################################

    # construct the argument parser and parse the arguments
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--video", help="path to the video file")
    ap.add_argument("-a", "--min-area", type=int, default=500, help="minimum area size")
    args = vars(ap.parse_args())

    alpha = 0
    trackers = []
    model = None
    kernel = np.ones((50, 20), np.uint8)
    flagRight = flagLeft = False

    # if the video argument is None, then we are reading from webcam
    if args.get("video", None) is None:
        camera = cv2.VideoCapture(0)
        time.sleep(0.25)
    # otherwise, we are reading from a video file
    else:
        camera = cv2.VideoCapture(args["video"])

    # loop over the frames of the video
    while True:
        ################################################################################################################
        ### 1) Grab a frame
        ################################################################################################################

        # grab the current frame
        (grabbed, frame) = camera.read()
        # if the frame could not be grabbed, then we have reached the end of the video
        if not grabbed:
            break

        ################################################################################################################
        ### 2) Pre-Processing
        ################################################################################################################

        # resize the frame, convert it to grayscale, and blur it
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        frame2show = frame.copy()
        # if the first frame is None, initialize it
        if model is None:
            model = gray
            continue

        ################################################################################################################
        ### 3) Track existing trackers, and update them
        ################################################################################################################
        for t in trackers:
            boundingbox = t.update(frame)
            boundingbox = map(int, boundingbox)


            ############################################################################################################
            ### 4) Look for
            ############################################################################################################

            # if a tracker got into the frame edges, remove it.
            # in addition, announce a movement about the relevant direction (left or right)

            edge = isEdge(boundingbox, [frame.shape[0], frame.shape[1]])
            if edge is not None:
                if edge is 'Right':
                    flagRight = True
                if edge is 'Left':
                    flagLeft = True
                trackers.remove(t)
            else:
                flagLeft = False
                flagRight = False

            cv2.rectangle(frame2show, (boundingbox[0], boundingbox[1]),
                     (boundingbox[0] + boundingbox[2], boundingbox[1] + boundingbox[3]), (0, 255, 255), 2)

            # if object is not moving much, remove it.
            # TODO!!!!!


        ################################################################################################################
        ### 5) Motion Detection assignment
        ################################################################################################################

        # compute the absolute difference between the current frame and first frame
        frameDelta = cv2.absdiff(model, gray)
        thresh = cv2.threshold(frameDelta,25, 255, cv2.THRESH_BINARY)[1]

        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, 2)
        (cnts, _) = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # loop over the contours
        for c in cnts:
            # if the contour is too small, ignore it
            if cv2.contourArea(c) < args["min_area"]:
                continue

            # compute the bounding box for the contour, draw it on the frame,
            # and update the text
            (x, y, w, h) = cv2.boundingRect(c)
            if x < 10 or x > (frame.shape[1]-10):
                continue
            aspect_ratio = float(h)/w
            if aspect_ratio < 1.5:
                continue
            cv2.rectangle(frame2show, (x, y), (x + w, y + h), (0, 255, 0), 2)

            #if a new object detect, start tracking on it
            if isNewObject([x,y,w,h], trackers):
                new_tracker = kcftracker.KCFTracker(False, False, True)
                new_tracker.init([x, y, w, h], frame)
                trackers.append(new_tracker)
                trackerInit = True


        model = cv2.addWeighted(model, 1 - alpha, gray, alpha, 0)

        ################################################################################################################
        ### 6) Display
        ################################################################################################################
        if flagLeft:
            cv2.putText(frame2show, "Motion Left", (10, 20),cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        if flagRight:
            cv2.putText(frame2show, "Motion Right", (10, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # show the frame and record if the user presses a key
        cv2.imshow("Image", frame2show)
        #cv2.imshow("Thresh", thresh)
        #cv2.imshow("Frame Delta", frameDelta)
        #cv2.imshow("Model", model)
        key = cv2.waitKey(1) & 0xFF

        # if the `q` key is pressed, break from the lop
        if key == ord("q"):
            break

    # cleanup the camera and close any open windows
    camera.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
	main()