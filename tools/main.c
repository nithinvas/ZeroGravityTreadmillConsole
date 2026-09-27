/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Belt-height controller for the zero-gravity treadmill
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  *
  * COMMANDS FROM THE CONSOLE
  * =========================
  *
  * The console (the mini PC) does not talk to this board directly. Commands
  * arrive over the load-cell board's USB cable and are relayed here as plain
  * bytes on USART2, 115200 8N1:
  *
  *   console --USB bulk OUT 0x02--> load-cell board --UART--> this board
  *
  * Every command is exactly 8 bytes, little-endian:
  *
  *   offset  size  field
  *   0       2     magic, 'H' 'T'
  *   2       1     opcode   0x01 MOVE_TO, 0x02 HOME, 0x03 STOP
  *   3       1     sequence, wraps at 256
  *   4       4     parameter, int32 -- millimetres for MOVE_TO, else 0
  *
  * A status frame of the same shape goes back the other way whenever the state
  * changes (opcode 0x81, byte 3 = state, parameter = height in mm, or -1 when
  * the position is not known). Nothing depends on it yet -- the relay is one
  * way today -- but it makes this board testable on a bench with nothing but a
  * USB-serial adapter.
  *
  * WHAT CHANGED FROM THE HARD-CODED VERSION
  * ========================================
  *
  *   * Heights are absolute, measured from the home switch, and the board
  *     tracks where it is. The old move_motor() travelled a distance from
  *     wherever the deck happened to be, which is only the same thing if
  *     homing has just run -- and homing was commented out.
  *   * Moves set the direction pins. The old code never did, so after homing
  *     (which points the motors down) every move drove further into the stops.
  *   * Moves can be interrupted. The old accelerate/cruise/decelerate loops
  *     busy-waited for up to 47 seconds without checking anything, so neither
  *     a STOP command nor a limit switch could reach them. They are now one
  *     loop that checks both on every pulse.
  *   * Travel is clamped here as well as in the console. The USB cable is one
  *     unplug away from delivering a half-written command.
  *
  * BEFORE THIS BUILDS
  * ==================
  *
  * USART2's global interrupt must be enabled: in CubeMX, NVIC Settings for
  * USART2, tick "USART2 global interrupt", and regenerate so that
  * USART2_IRQHandler() exists in stm32g0xx_it.c. The NVIC calls below are
  * harmless if MspInit already made them, but the handler itself has to be
  * generated -- without it, nothing is ever received.
  *
  * DIR_UP is a guess. Verify it on the hardware before trusting a move: with
  * the deck near the bottom, send a small MOVE_TO and check it rises.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <math.h>
#include <stdlib.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

typedef enum
{
    MOVE_COMPLETED = 0,   /* travelled the whole distance                     */
    MOVE_ABORTED,         /* a STOP command arrived                           */
    MOVE_LIMIT            /* a limit switch closed on the way down            */
} move_result_t;

typedef enum
{
    STATE_UNKNOWN = 0,    /* powered on, never homed: no absolute height yet  */
    STATE_IDLE,
    STATE_MOVING,
    STATE_HOMING
} board_state_t;

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define START_SPEED      200     // pulses/sec
#define MAX_SPEED        2000    // pulses/sec
#define STOP_SPEED       200     // pulses/sec

#define ACCELERATION     400     // pulses/sec^2
#define DECELERATION     400     // pulses/sec^2

#define PULSES_PER_MM    100     // 100 pulses = 1 mm

#define MAX_HOME_STEPS   74800

#define MOTOR1           1
#define MOTOR2           2

/* The travel, in millimetres. The console enforces the same range; this is the
 * copy that matters, because it is the one still standing if the cable is
 * pulled halfway through a command. */
#define MIN_HEIGHT_MM    20
#define MAX_HEIGHT_MM    750

/* Homing crawls at a fixed, slow rate: it stops on a switch, not on a count. */
#define HOME_DELAY_US    1000

/* Which level on STEP_DIR_* drives the deck upwards.
 *
 * DIR_DOWN follows the original move_to_home(), which drove toward the switches
 * with both direction pins RESET. DIR_UP is therefore its opposite -- but it is
 * an inference from that one line, not something measured. VERIFY IT. */
#define DIR_UP           GPIO_PIN_SET
#define DIR_DOWN         GPIO_PIN_RESET

/* Command protocol. Mirrors backend/trendmill/height/protocol.py. */
#define CMD_MAGIC_0      0x48    // 'H'
#define CMD_MAGIC_1      0x54    // 'T'
#define CMD_FRAME_SIZE   8

#define OP_MOVE_TO       0x01
#define OP_HOME          0x02
#define OP_STOP          0x03
#define OP_STATUS        0x81    // this board -> console

#define POSITION_UNKNOWN INT32_MIN
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
TIM_HandleTypeDef htim6;

UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */

volatile uint8_t home_reached_1 = 0; //false
volatile uint8_t home_reached_2 = 0; //false

/* Where the deck is, in pulses above the home switch. POSITION_UNKNOWN until
 * homing has run: an absolute height means nothing without a datum, and acting
 * on one anyway is how a deck gets driven into its end stops. Updated on every
 * pulse, so an interrupted move still leaves a usable position. */
static volatile int32_t position_pulses = POSITION_UNKNOWN;

/* Set from the receive interrupt, read inside the motion loop on every pulse.
 * This is the only way a move in progress can be stopped. */
static volatile uint8_t abort_requested = 0;

/* One pending command, filled by the interrupt and executed by the main loop.
 * Moves take tens of seconds, so they cannot run in interrupt context. */
static volatile uint8_t  pending_opcode = 0;
static volatile int32_t  pending_param  = 0;
static volatile uint8_t  last_seq       = 0;
static volatile uint8_t  have_last_seq  = 0;

/* Byte-at-a-time receive, with the frame assembled as it arrives. */
static uint8_t rx_byte;
static uint8_t rx_frame[CMD_FRAME_SIZE];
static uint8_t rx_count = 0;

static volatile board_state_t board_state = STATE_UNKNOWN;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_TIM6_Init(void);
/* USER CODE BEGIN PFP */

uint32_t calc_accel_pulses(void);
uint32_t calc_decel_pulses(void);

uint32_t calc_triangular_peak_speed(uint32_t travel_pulses);

static move_result_t run_profile(uint32_t travel_pulses, int8_t dir_sign);

void move_to_home(void);
void move_to_height(int32_t target_height_mm);

void stepper_delay_us(uint32_t us);
void step_single_motor(uint8_t motor, uint32_t delay);
void step_both_motors(uint32_t delay);

static void handle_rx_byte(uint8_t byte);
static void dispatch_pending(void);
static void send_status(void);
static int32_t position_mm(void);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART2_UART_Init();
  MX_TIM6_Init();
  /* USER CODE BEGIN 2 */
  HAL_TIM_Base_Start(&htim6);

  /* Nothing moves at power-on. The deck's position is unknown until the console
   * asks for homing, and a deck that repositions itself the moment the mains
   * comes back is not something to have in a clinic. */
  HAL_UART_Receive_IT(&huart2, &rx_byte, 1);
  send_status();

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    dispatch_pending();

    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSIDiv = RCC_HSI_DIV1;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief TIM6 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM6_Init(void)
{

  /* USER CODE BEGIN TIM6_Init 0 */

  /* USER CODE END TIM6_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM6_Init 1 */

  /* USER CODE END TIM6_Init 1 */
  htim6.Instance = TIM6;
  /* HSI is 16 MHz and the PLL is off, so a prescaler of 15 gives a 1 MHz
   * counter: one tick per microsecond, which every delay below assumes.
   * Changing the clock tree changes every speed in the motion profile. */
  htim6.Init.Prescaler = 15;
  htim6.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim6.Init.Period = 65535;
  htim6.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim6) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim6, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM6_Init 2 */

  /* USER CODE END TIM6_Init 2 */

}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  huart2.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart2.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  huart2.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&huart2, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&huart2, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* Receiving is the whole point of this port now. Harmless if MspInit has
   * already done it; the generated USART2_IRQHandler() is what actually has to
   * exist, and that comes from ticking the interrupt in CubeMX. */
  HAL_NVIC_SetPriority(USART2_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(USART2_IRQn);

  /* USER CODE END USART2_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, STEP_PULSE_2_Pin|STEP_DIR_2_Pin|STEP_PULSE_1_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(STEP_DIR_1_GPIO_Port, STEP_DIR_1_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : STEP_PULSE_2_Pin STEP_DIR_2_Pin STEP_PULSE_1_Pin */
  GPIO_InitStruct.Pin = STEP_PULSE_2_Pin|STEP_DIR_2_Pin|STEP_PULSE_1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : STEP_DIR_1_Pin */
  GPIO_InitStruct.Pin = STEP_DIR_1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(STEP_DIR_1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : LIMIT_2_Pin */
  GPIO_InitStruct.Pin = LIMIT_2_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(LIMIT_2_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : LIMIT_1_Pin */
  GPIO_InitStruct.Pin = LIMIT_1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(LIMIT_1_GPIO_Port, &GPIO_InitStruct);

  /* EXTI interrupt init*/
  HAL_NVIC_SetPriority(EXTI2_3_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI2_3_IRQn);

  HAL_NVIC_SetPriority(EXTI4_15_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(EXTI4_15_IRQn);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/*
 * ============================================================
 * COMMANDS IN
 * ============================================================
 */

/**
 * @brief  One byte from the console, in interrupt context.
 *
 * Frames are assembled here rather than in the main loop because a move blocks
 * the main loop for tens of seconds, and a STOP arriving during one has to be
 * acted on immediately. STOP is therefore handled right here; everything else
 * is parked for the main loop, which is the only place a motor may be driven.
 */
static void handle_rx_byte(uint8_t byte)
{
    /* Resynchronise on the magic. If the relay ever drops a byte or starts
     * mid-frame, this is what recovers -- without it the stream would be
     * permanently one byte out and every command misread. */
    if (rx_count == 0 && byte != CMD_MAGIC_0)
    {
        return;
    }
    if (rx_count == 1 && byte != CMD_MAGIC_1)
    {
        /* This byte may itself be the start of a real frame. */
        rx_count = (byte == CMD_MAGIC_0) ? 1 : 0;
        rx_frame[0] = CMD_MAGIC_0;
        return;
    }

    rx_frame[rx_count++] = byte;

    if (rx_count < CMD_FRAME_SIZE)
    {
        return;
    }
    rx_count = 0;

    uint8_t opcode = rx_frame[2];
    uint8_t seq    = rx_frame[3];

    int32_t param = (int32_t)((uint32_t)rx_frame[4]
                            | ((uint32_t)rx_frame[5] << 8)
                            | ((uint32_t)rx_frame[6] << 16)
                            | ((uint32_t)rx_frame[7] << 24));

    /* A repeat of the sequence we last acted on is a retransmit, not a second
     * instruction. Obeying it twice would move the deck twice. */
    if (have_last_seq && seq == last_seq)
    {
        return;
    }

    switch (opcode)
    {
        case OP_STOP:
            /* Immediate, and deliberately not queued: the point of STOP is that
             * it works while a move is running. */
            abort_requested = 1;
            last_seq = seq;
            have_last_seq = 1;
            break;

        case OP_MOVE_TO:
        case OP_HOME:
            /* One slot. A command arriving mid-move replaces any earlier
             * pending one rather than queueing, so the deck always does the
             * most recent thing asked of it. */
            pending_param  = param;
            pending_opcode = opcode;
            last_seq = seq;
            have_last_seq = 1;
            break;

        default:
            break;   /* not ours: ignore rather than guess */
    }
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART2)
    {
        handle_rx_byte(rx_byte);
        HAL_UART_Receive_IT(&huart2, &rx_byte, 1);
    }
}

/**
 * @brief  Re-arm after an error.
 *
 * An overrun stops reception dead on this part. Without this the board accepts
 * commands until the first noisy moment and is then silent forever, which looks
 * exactly like a dead board.
 */
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART2)
    {
        rx_count = 0;
        HAL_UART_Receive_IT(&huart2, &rx_byte, 1);
    }
}

/**
 * @brief  Run whatever the console last asked for. Main loop only.
 */
static void dispatch_pending(void)
{
    if (pending_opcode == 0)
    {
        return;
    }

    uint8_t opcode = pending_opcode;
    int32_t param  = pending_param;
    pending_opcode = 0;

    /* A STOP that arrived while this command was waiting applies to it. */
    abort_requested = 0;

    if (opcode == OP_HOME)
    {
        move_to_home();
    }
    else if (opcode == OP_MOVE_TO)
    {
        move_to_height(param);
    }
}

/*
 * ============================================================
 * STATUS OUT
 * ============================================================
 */

static int32_t position_mm(void)
{
    if (position_pulses == POSITION_UNKNOWN)
    {
        return -1;
    }
    return position_pulses / PULSES_PER_MM;
}

/**
 * @brief  Tell the console where the deck is and what it is doing.
 *
 * Same 8-byte shape as a command, opcode 0x81, with the state in the byte a
 * command uses for its sequence number.
 */
static void send_status(void)
{
    int32_t mm = position_mm();
    uint8_t frame[CMD_FRAME_SIZE];

    frame[0] = CMD_MAGIC_0;
    frame[1] = CMD_MAGIC_1;
    frame[2] = OP_STATUS;
    frame[3] = (uint8_t)board_state;
    frame[4] = (uint8_t)((uint32_t)mm & 0xFF);
    frame[5] = (uint8_t)(((uint32_t)mm >> 8) & 0xFF);
    frame[6] = (uint8_t)(((uint32_t)mm >> 16) & 0xFF);
    frame[7] = (uint8_t)(((uint32_t)mm >> 24) & 0xFF);

    HAL_UART_Transmit(&huart2, frame, CMD_FRAME_SIZE, 20);
}

/*
 * ============================================================
 * MOTION
 * ============================================================
 */

/**
 * @brief  Drive to an absolute height, measured from the home switch.
 *
 * Absolute, unlike the version this replaces: the distance travelled is the
 * difference against the tracked position, and the direction pins are set from
 * its sign. Asking for a height before homing does nothing -- there is no datum
 * to measure it from, and guessing would drive the deck into an end stop.
 */
void move_to_height(int32_t target_height_mm)
{
    if (position_pulses == POSITION_UNKNOWN)
    {
        send_status();   /* still STATE_UNKNOWN: the console must home first */
        return;
    }

    /* Clamped here as well as in the console. This copy is the one that still
     * applies when the cable is pulled halfway through a command. */
    if (target_height_mm < MIN_HEIGHT_MM)
    {
        target_height_mm = MIN_HEIGHT_MM;
    }
    if (target_height_mm > MAX_HEIGHT_MM)
    {
        target_height_mm = MAX_HEIGHT_MM;
    }

    int32_t delta_pulses = (target_height_mm * PULSES_PER_MM) - position_pulses;

    if (delta_pulses == 0)
    {
        return;
    }

    int8_t dir_sign = (delta_pulses > 0) ? 1 : -1;

    HAL_GPIO_WritePin(STEP_DIR_1_GPIO_Port, STEP_DIR_1_Pin,
                      (dir_sign > 0) ? DIR_UP : DIR_DOWN);
    HAL_GPIO_WritePin(STEP_DIR_2_GPIO_Port, STEP_DIR_2_Pin,
                      (dir_sign > 0) ? DIR_UP : DIR_DOWN);

    /* Moving away from the switches clears a stale closure, so that a limit hit
     * recorded on the way down does not abort the next move up. */
    if (dir_sign > 0)
    {
        home_reached_1 = 0;
        home_reached_2 = 0;
    }

    board_state = STATE_MOVING;
    send_status();

    run_profile((uint32_t)abs((int)delta_pulses), dir_sign);

    board_state = STATE_IDLE;
    send_status();
}

/**
 * @brief  Accelerate, cruise, decelerate -- checking for a reason to stop on
 *         every single pulse.
 *
 * The three phases were separate functions with no way out of any of them. A
 * full-travel move is around 47 seconds, and for that whole time the old code
 * could not see a STOP command or a limit switch: the EXTI callback set
 * home_reached_*, and nothing in the motion loops ever read it. That is what
 * drives a deck into its end stops.
 *
 * On a stop the speed is ramped down rather than cut, because dropping 2000
 * pulses/s to nothing loses steps, and lost steps mean the tracked position no
 * longer matches the deck.
 */
static move_result_t run_profile(uint32_t travel_pulses, int8_t dir_sign)
{
    uint32_t accel_pulses = calc_accel_pulses();
    uint32_t decel_pulses = calc_decel_pulses();
    uint32_t peak_speed   = MAX_SPEED;
    uint32_t cruise_pulses;

    if (travel_pulses >= (accel_pulses + decel_pulses))
    {
        cruise_pulses = travel_pulses - accel_pulses - decel_pulses;
    }
    else
    {
        /* TRIANGULAR: not enough distance to reach MAX_SPEED. */
        peak_speed = calc_triangular_peak_speed(travel_pulses);
        accel_pulses = (uint32_t)((((float)peak_speed * peak_speed)
                                 - ((float)START_SPEED * START_SPEED))
                                 / (2.0f * ACCELERATION));
        decel_pulses = travel_pulses - accel_pulses;
        cruise_pulses = 0;
    }

    uint32_t done = 0;
    float    cur_speed = START_SPEED;
    move_result_t result = MOVE_COMPLETED;

    while (done < travel_pulses)
    {
        if (abort_requested)
        {
            result = MOVE_ABORTED;
            break;
        }

        /* The limit switches sit at the bottom of the travel, so they only
         * matter on the way down -- but on the way down they are the last
         * thing between the motors and a mechanical stop. */
        if (dir_sign < 0 && (home_reached_1 || home_reached_2))
        {
            result = MOVE_LIMIT;
            break;
        }

        if (done < accel_pulses)
        {
            cur_speed = sqrtf(((float)START_SPEED * START_SPEED)
                              + (2.0f * ACCELERATION * done));
            if (cur_speed > (float)peak_speed)
            {
                cur_speed = (float)peak_speed;
            }
        }
        else if (done < accel_pulses + cruise_pulses)
        {
            cur_speed = (float)peak_speed;
        }
        else
        {
            uint32_t into_decel = done - accel_pulses - cruise_pulses;
            float    v_sq = ((float)peak_speed * peak_speed)
                          - (2.0f * DECELERATION * into_decel);
            cur_speed = (v_sq > ((float)STOP_SPEED * STOP_SPEED))
                      ? sqrtf(v_sq)
                      : (float)STOP_SPEED;
        }

        step_both_motors((uint32_t)(1000000.0f / (2.0f * cur_speed)));
        position_pulses += dir_sign;
        done++;
    }

    if (result != MOVE_COMPLETED)
    {
        /* Ramp down from wherever the speed had got to. */
        float v = cur_speed;
        while (v > (float)STOP_SPEED)
        {
            float v_sq = (v * v) - (2.0f * DECELERATION);
            v = (v_sq > ((float)STOP_SPEED * STOP_SPEED)) ? sqrtf(v_sq) : (float)STOP_SPEED;

            /* A limit switch means stop now, not coast further into it. */
            if (dir_sign < 0 && (home_reached_1 || home_reached_2))
            {
                break;
            }
            step_both_motors((uint32_t)(1000000.0f / (2.0f * v)));
            position_pulses += dir_sign;
        }
        abort_requested = 0;
    }

    if (result == MOVE_LIMIT)
    {
        /* The switch is the datum: wherever the console thought the deck was,
         * it is at the bottom now. */
        position_pulses = 0;
    }

    return result;
}

void stepper_delay_us(uint32_t us)
{
    /* TIM6 is 16-bit, so anything past 65535 us has to be waited out in
     * chunks. Nothing in the current profile gets close -- START_SPEED gives
     * 2500 us -- but the old uint16_t parameter would have wrapped silently if
     * anyone ever slowed it down. */
    while (us > 60000U)
    {
        uint16_t start = TIM6->CNT;
        while ((uint16_t)(TIM6->CNT - start) < 60000U)
        {
        }
        us -= 60000U;
    }

    uint16_t start = TIM6->CNT;
    while ((uint16_t)(TIM6->CNT - start) < (uint16_t)us)
    {
    }
}


uint32_t calc_accel_pulses(void)
{
    float max_speed = MAX_SPEED;
    float start_speed = START_SPEED;
    float acceleration = ACCELERATION;

    float accel_steps;

    accel_steps =
        (
            (max_speed * max_speed)
            -
            (start_speed * start_speed)
        )
        /
        (2.0f * acceleration);

    return (uint32_t)accel_steps;
}


uint32_t calc_decel_pulses(void)
{
    float max_speed = MAX_SPEED;
    float stop_speed = STOP_SPEED;
    float deceleration = DECELERATION;

    float decel_steps;

    decel_steps =
        (
            (max_speed * max_speed)
            -
            (stop_speed * stop_speed)
        )
        /
        (2.0f * deceleration);

    return (uint32_t)decel_steps;
}


/*
 * ============================================================
 * CALCULATE TRIANGULAR PEAK SPEED
 * ============================================================
 *
 * For a triangular profile:
 *
 *      START -> PEAK -> STOP
 *
 * There is no constant-speed section.
 *
 * The total distance is:
 *
 *      N = acceleration distance + deceleration distance
 *
 * Therefore:
 *
 *      N =
 *      (Vp^2 - Vs^2)/(2a)
 *      +
 *      (Vp^2 - Vf^2)/(2d)
 *
 * Solving for Vp:
 *
 *      Vp =
 *
 *      sqrt(
 *
 *          [2N + Vs^2/a + Vf^2/d]
 *          /
 *          [1/a + 1/d]
 *
 *      )
 *
 */

uint32_t calc_triangular_peak_speed(uint32_t travel_pulses)
{
    float N = (float)travel_pulses;

    float start_speed = (float)START_SPEED;
    float stop_speed = (float)STOP_SPEED;

    float acceleration = (float)ACCELERATION;
    float deceleration = (float)DECELERATION;

    float peak_speed;


    peak_speed =
        sqrtf(
            (
                (2.0f * N)
                +
                ((start_speed * start_speed) / acceleration)
                +
                ((stop_speed * stop_speed) / deceleration)
            )
            /
            (
                (1.0f / acceleration)
                +
                (1.0f / deceleration)
            )
        );


    /*
     * Safety limit:
     *
     * The triangular profile should never produce a peak
     * speed greater than MAX_SPEED.
     */

    if (peak_speed > MAX_SPEED)
    {
        peak_speed = MAX_SPEED;
    }


    return (uint32_t)peak_speed;
}


/*
 * MOVE TO HOME
 *
 * Crawls down until both limit switches close, calls that position zero, and
 * then lifts the deck to the bottom of its usable travel so that the console
 * and the board agree on a real height rather than on the switch itself.
 *
 * A run that gives up without finding the switches leaves the position unknown,
 * so the next height command is refused rather than measured from a datum that
 * was never established.
 */

void move_to_home(void)
{
    uint32_t home_steps = 0;

    board_state = STATE_HOMING;
    send_status();

    /* Clear previous home status */
    home_reached_1 = 0;
    home_reached_2 = 0;

    /* Check if already at home */
    if (HAL_GPIO_ReadPin(LIMIT_1_GPIO_Port, LIMIT_1_Pin) == GPIO_PIN_RESET)
    {
        home_reached_1 = 1;
    }

    if (HAL_GPIO_ReadPin(LIMIT_2_GPIO_Port, LIMIT_2_Pin) == GPIO_PIN_RESET)
    {
        home_reached_2 = 1;
    }

    /* Set direction toward home */
    HAL_GPIO_WritePin(STEP_DIR_1_GPIO_Port, STEP_DIR_1_Pin, DIR_DOWN);
    HAL_GPIO_WritePin(STEP_DIR_2_GPIO_Port, STEP_DIR_2_Pin, DIR_DOWN);

    while ((!home_reached_1 || !home_reached_2) && home_steps < MAX_HOME_STEPS)
    {
        if (abort_requested)
        {
            /* Stopped part way down: no datum was found, so the position stays
             * unknown and the console will have to home again. */
            abort_requested = 0;
            position_pulses = POSITION_UNKNOWN;
            board_state = STATE_UNKNOWN;
            send_status();
            return;
        }

        if (!home_reached_1)
        {
            step_single_motor(MOTOR1, HOME_DELAY_US);
        }

        if (!home_reached_2)
        {
            step_single_motor(MOTOR2, HOME_DELAY_US);
        }

        home_steps++;
    }

    if (!home_reached_1 || !home_reached_2)
    {
        /* Ran out of travel without finding both switches: a jam, a broken
         * switch, or a deck that was already at the top. Reporting this as
         * success would hand the console a datum that does not exist. */
        position_pulses = POSITION_UNKNOWN;
        board_state = STATE_UNKNOWN;
        send_status();
        return;
    }

    /* The switches are the datum. */
    position_pulses = 0;

    /* Lift clear of the switches to the bottom of the usable range, so that
     * "homed" means a height the console can name. */
    move_to_height(MIN_HEIGHT_MM);

    board_state = STATE_IDLE;
    send_status();
}


void step_single_motor(uint8_t motor,
				uint32_t delay){

	if(motor == MOTOR1){
        HAL_GPIO_WritePin(STEP_PULSE_1_GPIO_Port,STEP_PULSE_1_Pin,GPIO_PIN_SET);
        stepper_delay_us(delay);
        HAL_GPIO_WritePin(STEP_PULSE_1_GPIO_Port,STEP_PULSE_1_Pin,GPIO_PIN_RESET);
        stepper_delay_us(delay);
	}

	if(motor == MOTOR2){
        HAL_GPIO_WritePin(STEP_PULSE_2_GPIO_Port,STEP_PULSE_2_Pin,GPIO_PIN_SET);
        stepper_delay_us(delay);
        HAL_GPIO_WritePin(STEP_PULSE_2_GPIO_Port,STEP_PULSE_2_Pin,GPIO_PIN_RESET);
        stepper_delay_us(delay);
	}
}

void step_both_motors(uint32_t delay){
	HAL_GPIO_WritePin(STEP_PULSE_1_GPIO_Port, STEP_PULSE_1_Pin, GPIO_PIN_SET);
	HAL_GPIO_WritePin(STEP_PULSE_2_GPIO_Port, STEP_PULSE_2_Pin, GPIO_PIN_SET);
	stepper_delay_us(delay);
	HAL_GPIO_WritePin(STEP_PULSE_1_GPIO_Port, STEP_PULSE_1_Pin, GPIO_PIN_RESET);
	HAL_GPIO_WritePin(STEP_PULSE_2_GPIO_Port, STEP_PULSE_2_Pin, GPIO_PIN_RESET);
	stepper_delay_us(delay);
}
/*
 * LIMIT SWITCH INTERRUPT CALLBACK
 */

void HAL_GPIO_EXTI_Falling_Callback(uint16_t GPIO_Pin)
{
    if (GPIO_Pin == LIMIT_1_Pin)
    {
        home_reached_1 = 1;
    }

    if (GPIO_Pin == LIMIT_2_Pin)
    {
        home_reached_2 = 1;
    }

}


/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
