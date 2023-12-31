# HOW TO RUN
# python3 emotion_recognition.py -i video/novak_djokovic.mp4 --model output/model.pth --prototxt model/deploy.prototxt.txt --caffemodel model/res10_300x300_ssd_iter_140000_fp16.caffemodel


# import the necessary libraries
from torchvision.transforms import ToPILImage
from torchvision.transforms import Grayscale
from torchvision.transforms import ToTensor
from torchvision.transforms import Resize
from torchvision import transforms
from neuraspike import EmotionNet
import torch.nn.functional as nnf
from neuraspike import utils
import numpy as np
import argparse
import torch
import cv2

import base64
import os

from flask import Flask, render_template, send_from_directory, request
from flask_socketio import SocketIO, emit

from pymongo import MongoClient
from dotenv import load_dotenv
import threading
import time


# load our serialized model from disk
print("[INFO] loading model...")
net = cv2.dnn.readNetFromCaffe("model/deploy.prototxt.txt", "model/res10_300x300_ssd_iter_140000_fp16.caffemodel")

# check if gpu is available or not
device = "cuda" if torch.cuda.is_available() else "cpu"


emotion_dict = {0: "Enojo", 1: "Neutral", 2: "Asco", 3: "Miedo",
                4: "Felicidad", 5: "Tristeza", 6: "Sorpresa"}

# load the emotionNet weights
model = EmotionNet(num_of_channels=1, num_of_classes=len(emotion_dict))
model_weights = torch.load("output/model-CK3.pth")
model.load_state_dict(model_weights)
model.to(device)
model.eval()

# initialize a list of preprocessing steps to apply on each image during runtime
data_transform = transforms.Compose([
    ToPILImage(),
    Grayscale(num_output_channels=1),
    Resize((48, 48)),
    ToTensor()
])

load_dotenv()


app = Flask(__name__, static_folder="./templates/static")
app.config["SECRET_KEY"] = "secret!"
socketio = SocketIO(app, async_mode="eventlet")

mongodb_uri = os.environ.get('MONGODB_URI')


client = MongoClient(mongodb_uri)
db = client['TFM']
collection = db['pacientes']

selected_option = ""
fluctuating_variable = ""
# Variable global para indicar si el botón está activado o desactivado
button_status = False
# Variable global para controlar el hilo que envía los datos a la base de datos
thread_stop = threading.Event()


def store_data_in_db():
    global fluctuating_variable, thread_stop, additional_value, selected_option

    while not thread_stop.is_set():
        time.sleep(3)
        if button_status:

            
            # Separar la emoción y la probabilidad utilizando el método split()
            emocion, probabilidad_str = fluctuating_variable.split(":")
            # Limpiar la cadena de probabilidad para eliminar el símbolo de porcentaje (%)
            probabilidad_str = probabilidad_str.replace("%", "")

            # Convertir la probabilidad de string a un número de punto flotante (float)
            probabilidad = float(probabilidad_str)            



            # data_to_store = {'paciente': additional_value, 'value': fluctuating_variable, 'paciente': additional_value}
            data_to_store = {"paciente": {
                "nombre": additional_value,
                "emocion_detectada": emocion,
                "probabilidad": probabilidad,
                "emecion_esperada": selected_option
            }}
            collection.insert_one(data_to_store)


@app.route("/favicon.ico")
def favicon():
    """
    The favicon function serves the favicon.ico file from the static directory.

    :return: A favicon
    """
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


def base64_to_image(base64_string):
    """
    The base64_to_image function accepts a base64 encoded string and returns an image.
    The function extracts the base64 binary data from the input string, decodes it, converts
    the bytes to numpy array, and then decodes the numpy array as an image using OpenCV.

    :param base64_string: Pass the base64 encoded image string to the function
    :return: An image
    """
    base64_data = base64_string.split(",")[1]
    image_bytes = base64.b64decode(base64_data)
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    return image


@socketio.on("connect")
def test_connect():
    """
    The test_connect function is used to test the connection between the client and server.
    It sends a message to the client letting it know that it has successfully connected.

    :return: A 'connected' string
    """
    print("Connected")
    emit("my response", {"data": "Connected"})


def fluctuating_loop():

    @socketio.on("image")
    def receive_image(image):
        """
        The receive_image function takes in an image from the webcam, converts it to grayscale, and then emits
        the processed image back to the client.


        :param image: Pass the image data to the receive_image function
        :return: The image that was received from the client
        """
        # Decode the base64-encoded image data
        image = base64_to_image(image)

        # clone the current frame, convert it from BGR into RGB
        image = utils.resize_image(image, width=720, height=720)
        output = image.copy()
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # initialize an empty canvas to output the probability distributions
        canvas = np.zeros((350, 300, 3), dtype="uint8")

        # get the frame dimension, resize it and convert it to a blob
        (h, w) = image.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(
            image, (300, 300)), 1.0, (300, 300))

        # infer the blob through the network to get the detections and predictions
        net.setInput(blob)

        detections = net.forward()

        global fluctuating_variable
        # iterate over the detections
        for i in range(0, detections.shape[2]):

            # grab the confidence associated with the model's prediction
            confidence = detections[0, 0, i, 2]

            # eliminate weak detections, ensuring the confidence is greater
            # than the minimum confidence pre-defined
            if confidence > 0.5:

                # compute the (x,y) coordinates (int) of the bounding box for the face
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (start_x, start_y, end_x, end_y) = box.astype("int")

                # grab the region of interest within the image (the face),
                # apply a data transform to fit the exact method our network was trained,
                # add a new dimension (C, H, W) => (N, C, H, W) and send it to the device
                face = image[start_y:end_y, start_x:end_x]
                face = data_transform(face)
                face = face.unsqueeze(0)
                face = face.to(device)

                # infer the face (roi) into our pretrained model and compute the
                # probability score and class for each face and grab the readable
                # emotion detection
                predictions = model(face)
                prob = nnf.softmax(predictions, dim=1)
                top_p, top_class = prob.topk(1, dim=1)
                top_p, top_class = top_p.item(), top_class.item()

                # grab the list of predictions along with their associated labels
                emotion_prob = [p.item() for p in prob[0]]
                emotion_value = emotion_dict.values()

                # draw the probability distribution on an empty canvas initialized
                for (i, (emotion, prob)) in enumerate(zip(emotion_value, emotion_prob)):
                    prob_text = f"{emotion}: {prob * 100:.2f}%"
                    width = int(prob * 300)
                    cv2.rectangle(canvas, (5, (i * 50) + 5), (width, (i * 50) + 50),
                                  (0, 0, 255), -1)
                    cv2.putText(canvas, prob_text, (5, (i * 50) + 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

                # draw the bounding box of the face along with the associated emotion
                # and probability
                face_emotion = emotion_dict[top_class]
                ###########################
                face_text = f"{face_emotion}: {top_p * 100:.2f}%"
                fluctuating_variable = face_text
                socketio.emit('actualizar_valor', fluctuating_variable)

                ###########################
                cv2.rectangle(output, (start_x, start_y),
                              (end_x, end_y), (0, 255, 0), 2)
                y = start_y - 10 if start_y - 10 > 10 else start_y + 10
                cv2.putText(output, face_text, (start_x, y), cv2.FONT_HERSHEY_SIMPLEX,
                            1.05, (0, 255, 0), 2)

        frame_resized = cv2.resize(output, (640, 360))
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        result, frame_encoded = cv2.imencode(
            ".jpg", frame_resized, encode_param)
        processed_img_data = base64.b64encode(frame_encoded).decode()
        b64_src = "data:image/jpg;base64,"
        processed_img_data = b64_src + processed_img_data
        emit("processed_image", processed_img_data)

        frame_resized2 = cv2.resize(canvas, (640, 360))
        encode_param2 = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        result, frame_encoded2 = cv2.imencode(
            ".jpg", frame_resized2, encode_param2)
        processed_img_data2 = base64.b64encode(frame_encoded2).decode()
        b64_src2 = "data:image/jpg;base64,"
        processed_img_data2 = b64_src2 + processed_img_data2
        emit("processed_image2", processed_img_data2)


@app.route("/")
def index():

    global fluctuating_variable, button_status
    return render_template("index.html", fluctuating_variable=fluctuating_variable, button_status=button_status)


@app.route('/update_button_status', methods=['POST'])
def update_button_status():
    global button_status, additional_value, selected_option

    button_status = request.json['status']
    additional_value = request.json['additionalValue']
    selected_option = request.json['selectedOption']


    if button_status:
        # Iniciar el hilo para almacenar los datos en la base de datos mientras el botón esté activado
        thread_stop.clear()
        store_data_thread = threading.Thread(target=store_data_in_db)
        store_data_thread.start()
    else:
        # Detener el hilo cuando el botón cambie a desactivado
        thread_stop.set()

    return {'message': 'Button status updated successfully'}

# Ruta para recibir el valor fluctuante desde el servidor


@app.route('/get_fluctuating_variable', methods=['GET'])
def get_fluctuating_variable():
    global fluctuating_variable

    return {'value': fluctuating_variable}


if __name__ == "__main__":
    fluctuating_thread = threading.Thread(target=fluctuating_loop)
    fluctuating_thread.start()
    socketio.run(app, debug=True, port=5000, host='0.0.0.0')
