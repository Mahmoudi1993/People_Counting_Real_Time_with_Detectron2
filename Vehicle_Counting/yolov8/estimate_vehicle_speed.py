# Estimate vehicle Speed 
# You may need to restart your runtime prior to this, to let your installation take effect
# Some basic setup
# Setup yolov8 logger
import os
os.environ["KMP_DUPLICATE_LIB_OK"]="TRUE"


# import some common libraries
import cv2

import numpy as np
import supervision as sv

from tqdm import tqdm
from ultralytics import YOLO
from supervision.assets import VideoAssets, download_assets
from collections import defaultdict, deque


import ast
import sys
import random
import pandas as pd
from absl import app, flags, logging
from absl.flags import FLAGS

# Source and Target ROIs
SOURCE = np.array([
            [248, 510],
            [1552, 462],
            [1132, 290],
            [596, 314]
])

TARGET_WIDTH = 25
TARGET_HEIGHT = 250

TARGET = np.array([
    [0, 0],
    [TARGET_WIDTH - 1, 0],
    [TARGET_WIDTH - 1, TARGET_HEIGHT - 1],
    [0, TARGET_HEIGHT - 1],
])

# Transform Perspective
class ViewTransformer:

    def __init__(self, source: np.ndarray, target: np.ndarray) -> None:
        source = source.astype(np.float32)
        target = target.astype(np.float32)
        self.m = cv2.getPerspectiveTransform(source, target)

    def transform_points(self, points: np.ndarray) -> np.ndarray:
        if points.size == 0:
            return points

        reshaped_points = points.reshape(-1, 1, 2).astype(np.float32)
        transformed_points = cv2.perspectiveTransform(reshaped_points, self.m)
        return transformed_points.reshape(-1, 2)


FLAGS = flags.FLAGS

flags.DEFINE_string('video', None, 'path to input video or set to 0 for webcam')
flags.DEFINE_string('output', None, 'path to output video')
flags.DEFINE_integer('class_id', 0, 'class_id number to')
flags.DEFINE_integer('model_resolution', 1280, 'model_resolution')
flags.DEFINE_string('model', 'yolov8x.pt', 'pretrain model')
flags.DEFINE_string('output_format', 'XVID', 'codec used in VideoWriter when saving video to file')
flags.DEFINE_float('confidence_threshold', 0.3, 'confidence_threshold')
flags.DEFINE_float('iou_threshold', 0.5, 'iou_threshold')
flags.DEFINE_string('polygon','248, 500 ,1552, 300' , 'polygon threshold')


def main(argv): 
     
    # Configuration
    SOURCE_VIDEO_PATH = FLAGS.video
    TARGET_VIDEO_PATH = FLAGS.output
    CONFIDENCE_THRESHOLD = FLAGS.confidence_threshold
    IOU_THRESHOLD = FLAGS.iou_threshold
    MODEL_NAME = FLAGS.model
    MODEL_RESOLUTION = FLAGS.model_resolution
    Class_id = FLAGS.class_id
    Polygon = FLAGS.polygon

    model = YOLO(MODEL_NAME) 
    video_info = sv.VideoInfo.from_video_path(video_path=SOURCE_VIDEO_PATH)
    frame_generator = sv.get_video_frames_generator(source_path=SOURCE_VIDEO_PATH)

    # tracer initiation
    byte_track = sv.ByteTrack(
        frame_rate=video_info.fps, track_thresh=CONFIDENCE_THRESHOLD
    )

    # annotators configuration
    thickness = sv.calculate_dynamic_line_thickness(
        resolution_wh=video_info.resolution_wh
    )
    text_scale = sv.calculate_dynamic_text_scale(
        resolution_wh=video_info.resolution_wh
    )
    bounding_box_annotator = sv.BoundingBoxAnnotator(
        thickness=thickness
    )
    label_annotator = sv.LabelAnnotator(
        text_scale=text_scale,
        text_thickness=thickness,
        text_position=sv.Position.BOTTOM_CENTER
    )
    trace_annotator = sv.TraceAnnotator(
        thickness=thickness,
        trace_length=video_info.fps * 2,
        position=sv.Position.BOTTOM_CENTER
    )

    polygon_zone = sv.PolygonZone(
        polygon=SOURCE,
        frame_resolution_wh=video_info.resolution_wh
    )

    coordinates = defaultdict(lambda: deque(maxlen=video_info.fps))


    red = (0,0,255)
    blue = (255,0,0)

    # open target video
    with sv.VideoSink(TARGET_VIDEO_PATH, video_info) as sink:

        # loop over source video frame
        for frame in tqdm(frame_generator, total=video_info.total_frames):
            
            result = model(frame, imgsz=MODEL_RESOLUTION, verbose=False)[0]
            detections = sv.Detections.from_ultralytics(result)

            # filter out detections by class and confidence
            detections = detections[detections.confidence > CONFIDENCE_THRESHOLD]
            detections = detections[detections.class_id != Class_id]

            # filter out detections outside the zone
            detections = detections[polygon_zone.trigger(detections)]

            # refine detections using non-max suppression
            detections = detections.with_nms(IOU_THRESHOLD)

            # pass detection through the tracker
            detections = byte_track.update_with_detections(detections=detections)

            points = detections.get_anchors_coordinates(
                anchor=sv.Position.BOTTOM_CENTER
            )

            # calculate the detections position inside the target RoI
            points = view_transformer.transform_points(points=points).astype(int)

            # store detections position
            for tracker_id, [_, y] in zip(detections.tracker_id, points):
                coordinates[tracker_id].append(y)

            # format labels
            labels = []

            for tracker_id in detections.tracker_id:
                if len(coordinates[tracker_id]) < video_info.fps / 2:
                    color = red
                    labels.append(f"#{tracker_id}")

                else:
                    # calculate speed
                    color = blue
                    coordinate_start = coordinates[tracker_id][-1]
                    coordinate_end = coordinates[tracker_id][0]
                    distance = abs(coordinate_start - coordinate_end)
                    time = len(coordinates[tracker_id]) / video_info.fps
                    speed = distance / time * 3.6
                    labels.append(f"#{tracker_id} {int(speed)} km/h")

            res = ast.literal_eval(Polygon)
            detection_box = list(res)
    
            frame = frame.copy()
            detection_box = detection_box
            x1,y1,x2,y2 = detection_box
            blk = np.zeros(frame.shape, np.uint8)
            cv2.rectangle(blk, (x1, y1), (x2, y2), color, cv2.FILLED)
            annotated_frame = cv2.addWeighted(frame, 1.0, blk, 0.25, 1)

            annotated_frame = trace_annotator.annotate(
                scene=annotated_frame, detections=detections
            )
            annotated_frame = bounding_box_annotator.annotate(
                scene=annotated_frame, detections=detections
            )
            annotated_frame = label_annotator.annotate(
                scene=annotated_frame, detections=detections, labels=labels
            )
            
            # draw_polygon SOURCE
            #annotated_frame = sv.draw_polygon(scene=annotated_frame, polygon=SOURCE, color=sv.Color.white(), thickness=1)

            # add frame to target video
            sink.write_frame(annotated_frame)
            
        cv2.destroyAllWindows()
    return 

if __name__ == '__main__':
    app.run(main)