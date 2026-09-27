/* Stand-in for the CubeMX header, so the firmware's logic can be compiled and
 * tested on a desktop. Only what main.c actually touches. */
#ifndef STUB_MAIN_H
#define STUB_MAIN_H

#include <stdint.h>
#include <string.h>

typedef enum { GPIO_PIN_RESET = 0, GPIO_PIN_SET = 1 } GPIO_PinState;
typedef struct { int dummy; } GPIO_TypeDef;
typedef struct { uint32_t Pin, Mode, Pull, Speed; } GPIO_InitTypeDef;

typedef struct { volatile uint16_t CNT; } TIM_TypeDef;
/* Reading the counter advances it, so the firmware's busy-wait delays fall
 * straight through instead of spinning forever on a desktop. */
TIM_TypeDef *tim6_tick(void);
#define TIM6 tim6_tick()

typedef struct { void *Instance; struct {
    uint32_t BaudRate, WordLength, StopBits, Parity, Mode, HwFlowCtl,
             OverSampling, OneBitSampling, ClockPrescaler; } Init;
    struct { uint32_t AdvFeatureInit; } AdvancedInit; } UART_HandleTypeDef;
typedef struct { void *Instance; struct {
    uint32_t Prescaler, CounterMode, Period, AutoReloadPreload; } Init; } TIM_HandleTypeDef;
typedef struct { uint32_t MasterOutputTrigger, MasterSlaveMode; } TIM_MasterConfigTypeDef;
typedef struct { uint32_t OscillatorType, HSIState, HSIDiv, HSICalibrationValue;
                 struct { uint32_t PLLState; } PLL; } RCC_OscInitTypeDef;
typedef struct { uint32_t ClockType, SYSCLKSource, AHBCLKDivider, APB1CLKDivider; } RCC_ClkInitTypeDef;

#define HAL_OK 0
#define HAL_MAX_DELAY 0xFFFFFFFFU

/* Pins and ports. The numbers only have to be distinct. */
#define STEP_PULSE_1_Pin 0x0001
#define STEP_PULSE_2_Pin 0x0002
#define STEP_DIR_1_Pin   0x0004
#define STEP_DIR_2_Pin   0x0008
#define LIMIT_1_Pin      0x0010
#define LIMIT_2_Pin      0x0020
extern GPIO_TypeDef *const GPIOA, *const GPIOB, *const GPIOC, *const GPIOF;
#define STEP_PULSE_1_GPIO_Port GPIOB
#define STEP_PULSE_2_GPIO_Port GPIOB
#define STEP_DIR_1_GPIO_Port   GPIOA
#define STEP_DIR_2_GPIO_Port   GPIOB
#define LIMIT_1_GPIO_Port      GPIOC
#define LIMIT_2_GPIO_Port      GPIOC

#define USART2 ((void *)0x4000u)
#define TIM6_INSTANCE ((void *)0x5000u)
typedef enum { USART2_IRQn, EXTI2_3_IRQn, EXTI4_15_IRQn } IRQn_Type;

#define PWR_REGULATOR_VOLTAGE_SCALE1 0
#define RCC_OSCILLATORTYPE_HSI 0
#define RCC_HSI_ON 0
#define RCC_HSI_DIV1 0
#define RCC_HSICALIBRATION_DEFAULT 0
#define RCC_PLL_NONE 0
#define RCC_CLOCKTYPE_HCLK 1
#define RCC_CLOCKTYPE_SYSCLK 2
#define RCC_CLOCKTYPE_PCLK1 4
#define RCC_SYSCLKSOURCE_HSI 0
#define RCC_SYSCLK_DIV1 0
#define RCC_HCLK_DIV1 0
#define FLASH_LATENCY_0 0
#define TIM_COUNTERMODE_UP 0
#define TIM_AUTORELOAD_PRELOAD_DISABLE 0
#define TIM_TRGO_RESET 0
#define TIM_MASTERSLAVEMODE_DISABLE 0
#define UART_WORDLENGTH_8B 0
#define UART_STOPBITS_1 0
#define UART_PARITY_NONE 0
#define UART_MODE_TX_RX 0
#define UART_HWCONTROL_NONE 0
#define UART_OVERSAMPLING_16 0
#define UART_ONE_BIT_SAMPLE_DISABLE 0
#define UART_PRESCALER_DIV1 0
#define UART_ADVFEATURE_NO_INIT 0
#define UART_TXFIFO_THRESHOLD_1_8 0
#define UART_RXFIFO_THRESHOLD_1_8 0
#define GPIO_MODE_OUTPUT_PP 0
#define GPIO_MODE_IT_FALLING 1
#define GPIO_NOPULL 0
#define GPIO_SPEED_FREQ_LOW 0

#define __HAL_RCC_GPIOA_CLK_ENABLE() ((void)0)
#define __HAL_RCC_GPIOB_CLK_ENABLE() ((void)0)
#define __HAL_RCC_GPIOC_CLK_ENABLE() ((void)0)
#define __HAL_RCC_GPIOF_CLK_ENABLE() ((void)0)
#define __disable_irq() ((void)0)

int  HAL_Init(void);
void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pin, GPIO_PinState state);
GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *port, uint16_t pin);
void HAL_GPIO_Init(GPIO_TypeDef *port, GPIO_InitTypeDef *init);
void HAL_NVIC_SetPriority(IRQn_Type irq, uint32_t a, uint32_t b);
void HAL_NVIC_EnableIRQ(IRQn_Type irq);
int  HAL_PWREx_ControlVoltageScaling(uint32_t v);
int  HAL_RCC_OscConfig(RCC_OscInitTypeDef *s);
int  HAL_RCC_ClockConfig(RCC_ClkInitTypeDef *s, uint32_t l);
int  HAL_TIM_Base_Init(TIM_HandleTypeDef *h);
int  HAL_TIM_Base_Start(TIM_HandleTypeDef *h);
int  HAL_TIMEx_MasterConfigSynchronization(TIM_HandleTypeDef *h, TIM_MasterConfigTypeDef *c);
int  HAL_UART_Init(UART_HandleTypeDef *h);
int  HAL_UARTEx_SetTxFifoThreshold(UART_HandleTypeDef *h, uint32_t t);
int  HAL_UARTEx_SetRxFifoThreshold(UART_HandleTypeDef *h, uint32_t t);
int  HAL_UARTEx_DisableFifoMode(UART_HandleTypeDef *h);
int  HAL_UART_Receive_IT(UART_HandleTypeDef *h, uint8_t *buf, uint16_t n);
int  HAL_UART_Transmit(UART_HandleTypeDef *h, uint8_t *buf, uint16_t n, uint32_t timeout);
void Error_Handler(void);

#endif
