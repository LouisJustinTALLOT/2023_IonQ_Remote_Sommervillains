from collections import Counter
import qiskit
from qiskit import Aer
import qiskit.circuit.library
from qiskit import transpile, assemble
from qiskit.visualization import plot_histogram
from qiskit.circuit.library import RYGate

from matplotlib import pyplot as plt

import numpy as np
import math
from pprint import pprint

from typing import Dict, Union
import sympy as sy

from sklearn.metrics import mean_squared_error


# Image properties
SIZE = 28 # Image width
NB_PX_IMG = SIZE ** 2

# quantum parameters
N = math.ceil(math.log2(SIZE))
NBITS_PX_IDX = math.ceil(math.log2(NB_PX_IMG))
NB_QUBITS = 2 * N + 1
NB_PX = 2 ** (2 * N)

def load_images(path: str) -> np.ndarray:
    images = np.load(path)
    images = images / max(images.flatten()) * 255
    return images


def pixel_value_to_theta(pixel: float) -> float:
    return pixel / 255 * (np.pi / 2)


def theta_to_pixel_value(theta: float) -> int:
    return int(theta / (np.pi / 2) * 255)


def get_proba(counts: dict) -> dict:
    sums = sum(map(lambda x: x[1], counts.items()))
    return {key: value / sums for key, value in counts.items()}


def group_pixels_by_intensity(image: np.ndarray) -> dict:
    image = image.flatten()
    groups = {}
    for i in range(len(image)):
        intensity = image[i]
        if intensity not in groups:
            groups[intensity] = []
        groups[intensity].append("0b" + bin(i)[2:].zfill(NBITS_PX_IDX)) #.zfill(~) to pad with 0s TODO
        # optimization, remove # format
    return groups

def minimize_expression(expressions: list) -> str:
    """
    Minimize the boolean expression in the list
    For example:
    ['0b000000', '0b010000', '0b010000', '0b011000', '0b100000', '0b101000', '0b110000', '0b111000'] -> 0b000111
    """
    # sens reading?
    def translate(expression: str) -> str:
        logic_expression = "("
        start_idx = 2
        for i in range(start_idx, len(expression)):
            logic_expression += ("" if expression[-(i-start_idx+1)] == "1" else "~") + "m_" + str(i-start_idx) + "&"
        logic_expression = logic_expression[:-1] + ")"
        #print(expression, logic_expression)
        #input()
        return logic_expression
    problem = ""
    for expression in expressions:
        problem += translate(expression) + "|"
    problem = problem[:-1]
    print(problem)
    simplified_problem = str(sy.to_dnf(problem, simplify=True, force=True))
    print("Simplified problem: ", simplified_problem)
    simplified_expressions = []
    for expr in simplified_problem.split("|"):
        vars = expr.split("&")[1:-1]
        b_val = "".zfill(NBITS_PX_IDX)
        for var in vars:
            var = var.replace(" ", "")
            if var[0] != "~":
                idx = int(var[2:])
                b_val = b_val[:idx] + "1" + b_val[idx+1:]
        simplified_expressions.append(b_val)
    print(simplified_expressions)
    return simplified_expressions
    #return expressions


def process_image(image: np.ndarray) -> list:
    rounded_image = np.around(image, decimals=-1)
    intensity_to_pixels = group_pixels_by_intensity(rounded_image)
    print(len(intensity_to_pixels))
    intensity_count_expression = []
    for intensity, pixels in intensity_to_pixels.items():
        print(intensity)
        intensity_count_expression.append([intensity, len(pixels), minimize_expression(pixels)])

def encode(image: np.ndarray) -> qiskit.QuantumCircuit:
    circuit = qiskit.QuantumCircuit(NB_QUBITS)

    # Get the theta values for each pixel
    image = image.flatten()
    thetas = [pixel_value_to_theta(pixel) for pixel in image]
    thetas += [0] * (NB_PX - NB_PX_IMG)

    # Apply Hadamard gates for all qubits except the last one
    for i in range(NB_QUBITS - 1):
        circuit.h(i)
    circuit.barrier()

    ry_qbits = list(range(NB_QUBITS))

    # Switch is no longer relevant written this way: instead, we should apply the X gates according to
    # the result of process_image (see above)
    # intensity_count_expression = process_image(image)
    # switches = [ice[2][i] ^ ice[2][i-1] for i in range(intensity_count_expression)]
    # This also means that an optimisation has to be done to minimise the number of X gates applied 
    # (XOR yielding minimal number of 1s)
    switches = [bin(0)[2:].zfill(NB_QUBITS)] + [
        bin(i ^ (i - 1))[2:].zfill(NB_QUBITS) for i in range(1, NB_PX)
    ]

    # Apply the rotation gates
    for i in range(NB_PX):
        theta = thetas[i] # pixel_value_to_theta(intensity_count_expression[i][0])

        switch = switches[i]
        # Apply x gate to the i-th qubit if the i-th bit of the switch is 1
        for j in range(NB_QUBITS):
            if switch[j] == "1":
                circuit.x(j - 1)
        # TODO: Not a 2-qubit gate: reformulate using 2-qubit gates only (RYGate + CNOT)
        # Instead of 2 * theta, rotation is 2 * count * theta
        # where count is stored in intensity_count_expression[1]
        # where theta is result of pixel_value_to_theta(intensity_count_expression[0])
        c3ry = RYGate(2 * theta).control(NB_QUBITS - 1) # intensity_count_expression[i][1] * 2 * theta
        # {m_0, ..., m_i} ==> {R_{m_0}, ..., R_{m_i}} -> R_{m_0}*i+1 
        circuit.append(c3ry, ry_qbits)

        circuit.barrier()

    circuit.measure_all()
    return circuit


def decode(counts: dict) -> np.ndarray:
    histogram = get_proba(counts)
    img = np.zeros(NB_PX)  # we have a square image

    for i in range(NB_PX):
        print(i)
        bin_str: str = np.binary_repr(i, width=NB_QUBITS - 1)
        print(bin_str)
        cos_str = "0" + bin_str[::-1]
        sin_str = "1" + bin_str[::-1]

        if cos_str in histogram:
            prob_cos = histogram[cos_str]
            theta = math.acos(np.clip(2**N * math.sqrt(prob_cos), 0, 1))
        else:
            prob_cos = 0

        # not needed?
        if sin_str in histogram:
            prob_sin = histogram[sin_str]
            theta = math.asin(np.clip(2**N * math.sqrt(prob_sin), 0, 1))
        else:
            prob_sin = 0

        img[i] = theta_to_pixel_value(theta)

    img = img[:NB_PX_IMG]
    return img.reshape(SIZE, SIZE)


def simulator(circuit: qiskit.QuantumCircuit) -> dict:
    # Simulate the circuit
    aer_sim = Aer.get_backend("aer_simulator")
    t_qc = transpile(circuit, aer_sim)
    qobj = assemble(t_qc, shots=16384)

    result = aer_sim.run(qobj).result()
    return result.get_counts(circuit)


def run_part1(image: np.ndarray) -> Union[qiskit.QuantumCircuit, np.ndarray]:
    circuit = encode(image)
    counts = simulator(circuit)
    img = decode(counts)
    return circuit, img

def count_gates(circuit: qiskit.QuantumCircuit) -> Dict[int, int]:
    """Returns the number of gate operations with each number of qubits."""
    return Counter([len(gate[1]) for gate in circuit.data])

def image_mse(image1,image2):
    # Using sklearns mean squared error:
    # https://scikit-learn.org/stable/modules/generated/sklearn.metrics.mean_squared_error.html
    return mean_squared_error(image1, image2)

def grading(dataset):
    n=len(dataset)
    mse=0
    gatecount=0

    for data in dataset:
        circuit, image_re = run_part1(data['image'])
        # Count 2-qubit gates in circuit
        gatecount += count_gates(circuit)[2]
        
        # Calculate MSE
        mse += image_mse(data['image'],image_re)
        
    # Fidelity of reconstruction
    f = 1 - mse
    gatecount = gatecount / n

    # Score for Part 1
    return f * (0.999 ** gatecount)

if __name__ == "__main__":
    image = load_images("data/images.npy")[5]
    if image.max() != 0:
        image = image / image.max() * 255
    # plt.imshow(image, cmap='gray')
    # plt.show()

    # plt.imshow(image, cmap='gray')
    # plt.show()

    print(image)

    intensity_to_pixels = group_pixels_by_intensity(image)
    print(intensity_to_pixels)
    print(len(intensity_to_pixels))
    #test = [0b000000, 0b01000, 0b010000, 0b011000, 0b100000, 0b101000, 0b110000, 0b111000]
    print(process_image(image))
    # print(minimize_expression(intensity_to_pixels[0.])) # True
    # print(minimize_expression(intensity_to_pixels[55.])) # Not a single expression

    #image = np.array([0, 255, 0, 255, 0, 255, 0, 255, 0, 255, 0, 255, 0, 255, 0, 120])
    # image = np.array([128]*16)
    #image = image[:NB_PX]
    # print(image)

    # circuit = encode(image)
    # print(count_gates(circuit))

    # # Simulate the circuit
    # aer_sim = Aer.get_backend("aer_simulator")
    # t_qc = transpile(circuit, aer_sim)
    # qobj = assemble(t_qc, shots=16384)

    # result = aer_sim.run(qobj).result()
    # counts = result.get_counts(circuit)
    # print(counts)
    # print(len(counts))

    # # Decode the histogram
    # img = decode(get_proba(counts))
    # img = img.flatten()
    # print(img.flatten())
    # print(img[:28*(len(img) // 28)].reshape(len(img) // 28, 28))
    # print(img)
    # plt.hist(img.flatten())
    # plt.show()
