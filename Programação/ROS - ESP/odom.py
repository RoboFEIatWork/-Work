import json
import serial
import serial.tools.list_ports
import math
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from rclpy.logging import LoggingSeverity

from std_msgs.msg import Int32MultiArray
from geometry_msgs.msg import Twist, TransformStamped

from tf2_ros import TransformBroadcaster
from nav_msgs.msg import Odometry


class Ros2Serial(Node):
    def __init__(self, node_name="ros2serial_node"):
        super().__init__(node_name=node_name)
        
        self.get_logger().set_level(LoggingSeverity.INFO)
        
        # Parâmetros da porta serial
        self.declare_parameter('baud_rate', 9600)
        self.declare_parameter('serial_port', '/dev/ttyUSB1')
        self.baud_rate = self.get_parameter('baud_rate').value
        self.serial_port = self.get_parameter('serial_port').value
        self.ser = self.connect_to_serial(self.serial_port)
        
        # Envia o comando de reset para a ESP32 assim que o nó ROS 2 inicia
        if self.ser:
            self.ser.write(b'R')  # Envia 'R' como exemplo de comando de reset; adapte se necessário
        
        # Parâmetros do robô
        self.wheel_radius = 0.05  # Raio da roda em metros
        self.lx = 0.2355  # Distância entre rodas no eixo X
        self.ly = 0.15  # Distância entre rodas no eixo Y

        # Estado inicial do robô
        self.x = 0.0
        self.y = 0.0
        self.th = 0.0
        self.last_time = time.perf_counter()

        # Velocidades das rodas
        self.v1 = 0
        self.v2 = 0
        self.v3 = 0
        self.v4 = 0

        self.odom_broadcaster = TransformBroadcaster(self)
        self.timer = self.create_timer(0.1, self.broadcast_transform)
        
        # Configurações de tópicos ROS 2
        qos_profile = QoSProfile(depth=50)
        self.encoder_pub = self.create_publisher(Int32MultiArray, '/robot_base/encoders', qos_profile)
        self.odom_pub = self.create_publisher(Odometry, '/odom', qos_profile)
        
        self.subscription_cmd_vel = self.create_subscription(
            Twist,
            '/cmd_vel',
            self.listener_callback,
            qos_profile
        )
        
        # Thread para publicar mensagens e ler da serial
        self.publish_thread = threading.Thread(target=self.publish_messages)
        self.publish_thread.daemon = True  # Garante que a thread será encerrada com o nó
        self.publish_thread.start()

    #   Conecta com a serial do arduino
    def connect_to_serial(self, port):
        while rclpy.ok():
            try:
                self.ser = serial.Serial(port, self.baud_rate)
                self.get_logger().info(f"Conexão bem-sucedida com a porta serial {port}")
                self.ser.write(b'\x05')
                return self.ser
            except serial.SerialException as e:
                self.get_logger().error(f"Falha ao conectar com a porta serial: {e}")
            time.sleep(0.5)

    #   Recebe o json da ESP via serial
    def listener_callback(self, msg):
        data = {
            'linear_x': float(msg.linear.x),
            'linear_y': float(msg.linear.y),
            'linear_z': float(msg.linear.z),
            'angular_x': float(msg.angular.x),
            'angular_y': float(msg.angular.y),
            'angular_z': float(msg.angular.z)
        }

        json_data = json.dumps(data)
        try:
            if self.ser.isOpen():
                self.ser.write(json_data.encode('ascii'))
                self.ser.flush()
                self.get_logger().info("Comando de velocidade enviado com sucesso")
        except (serial.SerialException, serial.SerialTimeoutException) as e:
            self.get_logger().warn(f"Erro ao enviar comando: {e}")

    #   Verifica a mensagem recebida pela ESP, a leitura dos encoders
    def publish_messages(self):
        while rclpy.ok():
            try:
                if self.ser and self.ser.is_open:
                    line = self.ser.readline().decode("utf-8").strip()
                    if line:
                        data = json.loads(line)
                        if "encoders" in data:
                            self.get_logger().info("Publicando odometria")
                            self.publish_odometry(data)
                        else:
                            self.get_logger().info("Dados do encoder não recebidos")
            except (serial.SerialException, serial.SerialTimeoutException) as e:
                self.get_logger().warn(f"Conexão serial perdida: {e}")
                self.ser = self.connect_to_serial(self.serial_port)
            except Exception as e:
                self.get_logger().error(f"Erro inesperado: {e}")

    #   Calcula a velocidade das rodas para o Caramelo
    def publish_odometry(self, data):
        current_time = time.perf_counter()
        delta_time = current_time - self.last_time
        self.last_time = current_time
        try:
            #   Recebe o quanto de volta a roda rodou e com base nisso calcula a velocidade da roda,
            # levando em consideracao o tempo decorrido
            self.v1 =  float(data["encoders"][0]) * (1/delta_time) * 2 * math.pi * self.wheel_radius
            self.v2 = -float(data["encoders"][1]) * (1/delta_time) * 2 * math.pi * self.wheel_radius
            self.v3 =  float(data["encoders"][2]) * (1/delta_time) * 2 * math.pi * self.wheel_radius
            self.v4 = -float(data["encoders"][3]) * (1/delta_time) * 2 * math.pi * self.wheel_radius

        except (ValueError, KeyError) as e:
            self.get_logger().error(f"Erro ao processar encoders: {e}")
            self.v1 = 0
            self.v2 = 0
            self.v3 = 0
            self.v4 = 0

        # Mecanum Inverse Kinematics
        vx  = (+ self.v1 + self.v2 + self.v3 + self.v4) / 4
        vy  = (- self.v1 + self.v2 + self.v3 - self.v4) / 4
        vth = (- self.v1 + self.v2 - self.v3 + self.v4) / (4 * (self.lx + self.ly))

        # Error Correction
        if abs(vx) < 0.015: vx = 0
        if abs(vy) < 0.015: vy = 0
        if abs(vth) < 0.015: vth = 0

        self.computeOdom(vx, vy, vth, delta_time) 

    def euler_to_quaternion(self, roll, pitch, yaw):
        if not all(isinstance(i, (int, float)) for i in [roll, pitch, yaw]):
            self.get_logger().error(f"Entradas inválidas para conversão para quaternion: {roll}, {pitch}, {yaw}")
            return (0.0, 0.0, 0.0, 1.0)  # Valor default

        qx = math.sin(roll / 2) * math.cos(pitch / 2) * math.cos(yaw / 2) - math.cos(roll / 2) * math.sin(pitch / 2) * math.sin(yaw / 2)
        qy = math.cos(roll / 2) * math.sin(pitch / 2) * math.cos(yaw / 2) + math.sin(roll / 2) * math.cos(pitch / 2) * math.sin(yaw / 2)
        qz = math.cos(roll / 2) * math.cos(pitch / 2) * math.sin(yaw / 2) - math.sin(roll / 2) * math.sin(pitch / 2) * math.cos(yaw / 2)
        qw = math.cos(roll / 2) * math.cos(pitch / 2) * math.cos(yaw / 2) + math.sin(roll / 2) * math.sin(pitch / 2) * math.sin(yaw / 2)
        return qx, qy, qz, qw

    #   Calcula a odometria para o Caramelo
    def computeOdom(self, vx, vy, vth, dt):
        # Atualização incremental da posição e orientação
        delta_x = (vx * math.cos(self.th) - vy * math.sin(self.th)) * dt
        delta_y = (vx * math.sin(self.th) + vy * math.cos(self.th)) * dt
        delta_th = vth * dt

        self.x += delta_x
        self.y += delta_y  # Removendo o sinal negativo (ajuste)
        self.th += delta_th

        # Publicando a mensagem de Odometria
        odom_msg = Odometry()
        odom_msg.header.stamp = self.get_clock().now().to_msg()
        odom_msg.header.frame_id = 'odom'  # Frame global
        odom_msg.child_frame_id = 'base_footprint'  # Frame local do robô

        # Definindo posição e orientação
        odom_msg.pose.pose.position.x = self.x
        odom_msg.pose.pose.position.y = self.y
        odom_msg.pose.pose.position.z = 0.0
        q = self.euler_to_quaternion(0.0, 0.0, self.th)
        odom_msg.pose.pose.orientation.x = q[0]
        odom_msg.pose.pose.orientation.y = q[1]
        odom_msg.pose.pose.orientation.z = q[2]
        odom_msg.pose.pose.orientation.w = q[3]

        # Definindo velocidades lineares e angulares
        odom_msg.twist.twist.linear.x = vx
        odom_msg.twist.twist.linear.y = vy
        odom_msg.twist.twist.linear.z = 0.0
        odom_msg.twist.twist.angular.x = 0.0
        odom_msg.twist.twist.angular.y = 0.0
        odom_msg.twist.twist.angular.z = vth

        # Publicando a odometria
        self.odom_pub.publish(odom_msg)
        self.get_logger().info(f"Odometry publicada: x={self.x:.2f}, y={self.y:.2f}, theta={self.th:.2f}")

        # Publicando a transformação (TF)
        t = TransformStamped()
        t.header.stamp = odom_msg.header.stamp  # Sincronizado com a odometria
        t.header.frame_id = 'odom'
        t.child_frame_id = 'base_footprint'

        # Definindo a translação
        t.transform.translation.x = self.x
        t.transform.translation.y = self.y
        t.transform.translation.z = 0.0

        # Definindo a rotação
        t.transform.rotation.x = q[0]
        t.transform.rotation.y = q[1]
        t.transform.rotation.z = q[2]
        t.transform.rotation.w = q[3]

        self.odom_broadcaster.sendTransform(t)

#   Funcao main
def main(args=None):
    rclpy.init(args=args)
    node = Ros2Serial()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Interrupção por teclado')
    finally:
        node.ser.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()