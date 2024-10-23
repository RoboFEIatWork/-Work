//bibliotrcsa
#include <stdio.h>
#include <ESP32Encoder.h>
#include <ArduinoJson.h>

#define ENCODER_PERIOD 100 //amostragem de tempo

#define PULSES_PER_ROTATION 1024
#define MOTOR_REDUCTION 28

// Motor Inferior Direito
#define Pino_RR_A 18 
#define Pino_RR_B 19 
#define Pino_RR_PWM 2

// Motor Inferior Esquerdo
#define Pino_RL_A 26 
#define Pino_RL_B 27 
#define Pino_RL_PWM 13


// Definaçao dos Encoders
ESP32Encoder encoder_RR;
ESP32Encoder encoder_RL;

int pwmRR = 512;
int pwmRL = 546;

//globais
long prevTRR = 0;
long prevTRL = 0;
long prevTFR = 0;
long prevTFL = 0;
int posPrevRR = 0;
int posPrevRL = 0;
int posPrevFR = 0;
int posPrevFL = 0;

float encoder_time = 0;

//Velocity PI control
float Kp = 1.0;
float Ki = 0.01;

float erroRR = 0;
float erroRL = 0;
float erroFR = 0;
float erroFL = 0;
float erroIntRR = 0; //erro integral
float erroIntRL = 0; //erro integral
float erroIntFR = 0; //erro integral
float erroIntFL = 0; //erro integral


//variáveis para o filtro
float rpm_filtradoRR = 0;
float rpm_previoRR = 0;

//variáveis para o filtro
float rpm_filtradoRL = 0;
float rpm_previoRL = 0;

//variáveis para o filtro
float rpm_filtradoFR = 0;
float rpm_previoFR = 0;

//variáveis para o filtro
float rpm_filtradoLF = 0;
float rpm_previoFL = 0;


void clearEncoder() {
  encoder_RR.clearCount();
  encoder_RL.clearCount();
}

float target_rpm(){
  float target_rpm = 0;

  // if (motorIdx % 2 == 0){
  //   target_rpm = target_rpm * -1 
  // }

  return target_rpm;
}


float CalcControlSignal(float rpm, float& rpm_previo, float& rpm_filtrado, float target_rpm,float& erro, float& erroInt) {
  // Filtro passa-baixa de 25Hz
  rpm_filtrado = 0.854 * rpm_filtrado + 0.0728 * rpm + 0.0728 * rpm_previo;
  rpm_previo = rpm;

  // Cálculo do erro
  erro = target_rpm - rpm_filtrado;
  erroInt += erro * ENCODER_PERIOD;
  
  // Calcula o sinal de controle u(s)
  float u_s = Kp * erro + Ki * erroInt;

  return u_s;
}

// Função para calcular a velocidade em RPM
void CalcSpeed() { 
  // Pega a posicao atual dos encoders
  int posRR = encoder_RR.getCount();
  int posRL = encoder_RL.getCount();

  // Calcula a diferença de posição entre a leitura atual e a leitura anterior
  int deltaPosRR = posRR - posPrevRR;
  int deltaPosRL = posRL - posPrevRL;
  
  // Converte a diferença de posição para rotações (dividido pelos pulsos por rotação e a redução do motor)
  float rotationsRR = (float)deltaPosRR / (PULSES_PER_ROTATION * 2 * MOTOR_REDUCTION);
  float rotationsRL = (float)deltaPosRL / (PULSES_PER_ROTATION * 2 * MOTOR_REDUCTION);
  
  // Calcula a velocidade em rotações por minuto (RPM) com base no período de amostragem
  float rpmRR = (rotationsRR / (ENCODER_PERIOD / 1000.0)) * 60; // ENCODER_PERIOD está em ms, então dividimos por 1000 para converter para segundos
  float rpmRL = (rotationsRL / (ENCODER_PERIOD / 1000.0)) * 60; // ENCODER_PERIOD está em ms, então dividimos por 1000 para converter para segundos
  
  // Chama a função para calcular o sinal de controle e filtrar o RPM
  float u_s_RR = CalcControlSignal(rpmRR, rpm_previoRR, rpm_filtradoRR, target_rpm(), erroRR, erroIntRR);
  float u_s_RL = CalcControlSignal(rpmRL, rpm_previoRL, rpm_filtradoRL, -target_rpm(), erroRL, erroIntRL);

  // Atualiza a posição anterior
  posPrevRR = posRR; 
  posPrevRL = posRL; 

  float pwmVal[2] = {Pino_RR_PWM,Pino_RL_PWM};
  float pwm[2] = {pwmRR,pwmRL};
  float u_s[2] = {u_s_RR,u_s_RL};

  for(int i = 0; i < 2; i++){
    pwm[i] = pwm[i] + u_s[i];

    if(pwm[i] < 0){
      pwm[i] = 0;
    }
    if(pwm[i] > 1024){
      pwm[i] = 1024;
    }
    ledcWrite(pwmVal[i], pwm[i]);
  }
  // //seta a velocidade e direção do motor
  // int dir = 1;
  // if(u_s<0){
  //   dir = -1;
  // }
  

  // TODO: fazer a implementacao do setMotor
  // setMotor(Pino_RR_PWM, pwrRR);

  // Imprime a posição e a velocidade em RPM
  // Serial.println(u_s[1]);
  // Serial.println(u_s[0]);

    // Imprime os valores no Serial Plotter
  Serial.print(target_rpm()); // Imprime o valor do motor direito
  Serial.print(",");
  Serial.print(rpmRR); // Imprime o valor do motor esquerdo
  Serial.println();
  // Serial.println(target_rpm());
  // Serial.println(-target_rpm());

  // Serial.println(rpmRR);
  // Serial.println(rpmRL);
}

void setup() {
  // put your setup code here, to run once:
  Serial.begin(9600);

    // Configuração dos pinos de entrada (sensores de encoders)
  pinMode(Pino_RR_A, INPUT);
  pinMode(Pino_RR_B, INPUT);
  pinMode(Pino_RL_A, INPUT);
  pinMode(Pino_RL_B, INPUT);

  // Configuração dos pinos de saída (PWM para controle dos motores)
  pinMode(Pino_RR_PWM, OUTPUT);
  pinMode(Pino_RL_PWM, OUTPUT);

  // Configura os canais PWM para os motores
  ////ledcSetup(canal_RR_PWM, frequencia_PWM, resolucao_PWM); // Configura o canal RR_PWM
  ledcAttachChannel(Pino_RR_PWM, 500, 10, 0); // Associa o pino PWM ao canal RR

  /////ledcSetup(canal_RL_PWM, frequencia_PWM, resolucao_PWM); // Configura o canal RL_PWM
  ledcAttachChannel(Pino_RL_PWM, 500, 10 ,1); // Associa o pino PWM ao canal RL
  
  //
  ledcWrite(Pino_RR_PWM, pwmRR);
  ledcWrite(Pino_RL_PWM, pwmRL);
  
  //
  encoder_RR.attachHalfQuad(Pino_RR_A, Pino_RR_B);
  encoder_RL.attachHalfQuad(Pino_RL_A, Pino_RL_B);

  clearEncoder();

}

void loop() {
  // put your main code here, to run repeatedly:

  if(millis() - encoder_time >= ENCODER_PERIOD){
    
    CalcSpeed();

    encoder_time = millis();
  }
  

}
