/* Compiles the height firmware's logic on a desktop and exercises it.
 *
 * The HAL is stubbed (main.h here), the step pulses are counted instead of
 * driven, and TIM6 advances on read so the busy-wait delays return at once.
 * What is actually under test is the part that would otherwise only be
 * testable by watching a deck move: framing, direction, distance, position
 * tracking, and every reason a move should stop early.
 *
 *   cc -I tools/test -o /tmp/tfw tools/test/test_firmware.c -lm && /tmp/tfw
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include "main.h"

/* ---- the fake machine ---------------------------------------------------- */

static TIM_TypeDef tim6_regs;
TIM_TypeDef *tim6_tick(void) { tim6_regs.CNT += 30000; return &tim6_regs; }
static GPIO_TypeDef ports[4];
GPIO_TypeDef *const GPIOA = &ports[0];
GPIO_TypeDef *const GPIOB = &ports[1];
GPIO_TypeDef *const GPIOC = &ports[2];
GPIO_TypeDef *const GPIOF = &ports[3];

static int      pulses_1, pulses_2;
static GPIO_PinState dir_1, dir_2;
static GPIO_PinState limit_1_level = GPIO_PIN_SET;   /* SET = not pressed */
static GPIO_PinState limit_2_level = GPIO_PIN_SET;
/* Close the limit switches after this many down-pulses; -1 = never. */
static int      limit_after = -1;
static int      down_pulses;
static uint8_t  tx_frames[64][8];
static int      tx_count;
static void maybe_stop(void);
void HAL_GPIO_EXTI_Falling_Callback(uint16_t pin);   /* lives in main.c */

void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pin, GPIO_PinState state)
{
    (void)port;
    if (pin == STEP_DIR_1_Pin) dir_1 = state;
    if (pin == STEP_DIR_2_Pin) dir_2 = state;
    if (pin == STEP_PULSE_1_Pin && state == GPIO_PIN_SET) {
        pulses_1++;
        if (dir_1 == GPIO_PIN_RESET) {
            down_pulses++;
            if (limit_after >= 0 && down_pulses >= limit_after) {
                limit_1_level = limit_2_level = GPIO_PIN_RESET;
                HAL_GPIO_EXTI_Falling_Callback(LIMIT_1_Pin);
                HAL_GPIO_EXTI_Falling_Callback(LIMIT_2_Pin);
            }
        }
    }
    if (pin == STEP_PULSE_2_Pin && state == GPIO_PIN_SET) pulses_2++;
    maybe_stop();
}

GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *port, uint16_t pin)
{
    (void)port;
    if (pin == LIMIT_1_Pin) return limit_1_level;
    if (pin == LIMIT_2_Pin) return limit_2_level;
    return GPIO_PIN_SET;
}

int  HAL_Init(void) { return HAL_OK; }
void HAL_GPIO_Init(GPIO_TypeDef *p, GPIO_InitTypeDef *i) { (void)p; (void)i; }
void HAL_NVIC_SetPriority(IRQn_Type q, uint32_t a, uint32_t b) { (void)q;(void)a;(void)b; }
void HAL_NVIC_EnableIRQ(IRQn_Type q) { (void)q; }
int  HAL_PWREx_ControlVoltageScaling(uint32_t v) { (void)v; return HAL_OK; }
int  HAL_RCC_OscConfig(RCC_OscInitTypeDef *s) { (void)s; return HAL_OK; }
int  HAL_RCC_ClockConfig(RCC_ClkInitTypeDef *s, uint32_t l) { (void)s;(void)l; return HAL_OK; }
int  HAL_TIM_Base_Init(TIM_HandleTypeDef *h) { (void)h; return HAL_OK; }
int  HAL_TIM_Base_Start(TIM_HandleTypeDef *h) { (void)h; return HAL_OK; }
int  HAL_TIMEx_MasterConfigSynchronization(TIM_HandleTypeDef *h, TIM_MasterConfigTypeDef *c)
{ (void)h;(void)c; return HAL_OK; }
int  HAL_UART_Init(UART_HandleTypeDef *h) { (void)h; return HAL_OK; }
int  HAL_UARTEx_SetTxFifoThreshold(UART_HandleTypeDef *h, uint32_t t) { (void)h;(void)t; return HAL_OK; }
int  HAL_UARTEx_SetRxFifoThreshold(UART_HandleTypeDef *h, uint32_t t) { (void)h;(void)t; return HAL_OK; }
int  HAL_UARTEx_DisableFifoMode(UART_HandleTypeDef *h) { (void)h; return HAL_OK; }
int  HAL_UART_Receive_IT(UART_HandleTypeDef *h, uint8_t *b, uint16_t n) { (void)h;(void)b;(void)n; return HAL_OK; }
int  HAL_UART_Transmit(UART_HandleTypeDef *h, uint8_t *b, uint16_t n, uint32_t t)
{
    (void)h; (void)t;
    if (tx_count < 64 && n == 8) memcpy(tx_frames[tx_count++], b, 8);
    return HAL_OK;
}
/* The firmware, with its entry point renamed out of the way. */
#define main firmware_main
#include "../main.c"
#undef main

/* ---- helpers -------------------------------------------------------------- */

/* A stop raised part way through a move, standing in for the interrupt. */
static int stop_after_pulses;
static void maybe_stop(void)
{
    if (stop_after_pulses > 0 && pulses_1 >= stop_after_pulses) abort_requested = 1;
}

static int failures;
#define CHECK(cond, ...) do { if (!(cond)) { \
    printf("  FAIL: "); printf(__VA_ARGS__); printf("\n"); failures++; } } while (0)

static void reset_machine(void)
{
    pulses_1 = pulses_2 = down_pulses = tx_count = 0;
    limit_after = -1;
    limit_1_level = limit_2_level = GPIO_PIN_SET;
    home_reached_1 = home_reached_2 = 0;
    position_pulses = POSITION_UNKNOWN;
    abort_requested = 0;
    pending_opcode = 0;
    have_last_seq = 0;
    rx_count = 0;
    board_state = STATE_UNKNOWN;
}

static void feed(uint8_t opcode, int32_t param, uint8_t seq)
{
    uint8_t f[8] = { 0x48, 0x54, opcode, seq,
                     (uint8_t)(param), (uint8_t)(param >> 8),
                     (uint8_t)(param >> 16), (uint8_t)(param >> 24) };
    for (int i = 0; i < 8; i++) handle_rx_byte(f[i]);
}

static void home_the_deck(void)
{
    limit_after = 50;           /* switches close 50 pulses down */
    move_to_home();
    limit_after = -1;
    limit_1_level = limit_2_level = GPIO_PIN_SET;
    home_reached_1 = home_reached_2 = 0;
    pulses_1 = pulses_2 = down_pulses = 0;
}

/* ---- the tests ------------------------------------------------------------ */

static void test_frame_parsing(void)
{
    printf("a command is decoded from the byte stream\n");
    reset_machine();
    feed(OP_MOVE_TO, 300, 1);
    CHECK(pending_opcode == OP_MOVE_TO, "opcode not queued");
    CHECK(pending_param == 300, "param was %d, expected 300", (int)pending_param);
}

static void test_resync(void)
{
    printf("a frame is still found after junk on the line\n");
    reset_machine();
    /* The relay may drop bytes or be joined mid-stream. Without resync the
     * board would be permanently one byte out and misread every command. */
    handle_rx_byte(0x00); handle_rx_byte(0xFF); handle_rx_byte(0x48);
    feed(OP_MOVE_TO, 450, 2);
    CHECK(pending_opcode == OP_MOVE_TO, "did not resynchronise");
    CHECK(pending_param == 450, "param was %d, expected 450", (int)pending_param);
}

static void test_duplicate_sequence_ignored(void)
{
    printf("a retransmitted command is not obeyed twice\n");
    reset_machine();
    feed(OP_MOVE_TO, 300, 5);
    pending_opcode = 0;
    feed(OP_MOVE_TO, 300, 5);
    CHECK(pending_opcode == 0, "acted on a repeat of sequence 5");
    feed(OP_MOVE_TO, 300, 6);
    CHECK(pending_opcode == OP_MOVE_TO, "ignored a genuinely new command");
}

static void test_stop_is_immediate(void)
{
    printf("STOP is actioned in the interrupt, not queued\n");
    reset_machine();
    feed(OP_STOP, 0, 9);
    CHECK(abort_requested == 1, "STOP did not raise the abort flag");
    CHECK(pending_opcode == 0, "STOP should not wait for the main loop");
}

static void test_no_move_before_homing(void)
{
    printf("a height is refused until the deck has been homed\n");
    reset_machine();
    move_to_height(300);
    CHECK(pulses_1 == 0, "moved %d pulses with no datum", pulses_1);
    CHECK(position_pulses == POSITION_UNKNOWN, "invented a position");
}

static void test_homing_sets_the_datum(void)
{
    printf("homing finds the switches and leaves the deck at the minimum\n");
    reset_machine();
    home_the_deck();
    CHECK(position_pulses == MIN_HEIGHT_MM * PULSES_PER_MM,
          "position after homing was %d pulses, expected %d",
          (int)position_pulses, MIN_HEIGHT_MM * PULSES_PER_MM);
    CHECK(board_state == STATE_IDLE, "state after homing was %d", (int)board_state);
}

static void test_homing_that_finds_nothing_reports_unknown(void)
{
    printf("homing that never finds a switch does not claim success\n");
    reset_machine();
    limit_after = -1;                 /* switches never close */
    move_to_home();
    CHECK(position_pulses == POSITION_UNKNOWN, "claimed a datum it never found");
    CHECK(board_state == STATE_UNKNOWN, "state was %d, expected UNKNOWN", (int)board_state);
}

static void test_absolute_move_up(void)
{
    printf("a height is absolute, and sets the direction pins\n");
    reset_machine();
    home_the_deck();
    move_to_height(300);
    CHECK(dir_1 == DIR_UP && dir_2 == DIR_UP, "direction pins were not set to up");
    CHECK(position_pulses == 300 * PULSES_PER_MM,
          "ended at %d pulses, expected %d", (int)position_pulses, 300 * PULSES_PER_MM);
    /* 20 mm -> 300 mm is 280 mm, not 300: the old code travelled the target. */
    CHECK(pulses_1 == 280 * PULSES_PER_MM,
          "travelled %d pulses, expected %d", pulses_1, 280 * PULSES_PER_MM);
    CHECK(pulses_1 == pulses_2, "the two motors did not step together");
}

static void test_absolute_move_down(void)
{
    printf("a lower height drives the other way\n");
    reset_machine();
    home_the_deck();
    move_to_height(400);
    int before = pulses_1;
    move_to_height(250);
    CHECK(dir_1 == DIR_DOWN, "direction was not set to down");
    CHECK(position_pulses == 250 * PULSES_PER_MM,
          "ended at %d pulses", (int)position_pulses);
    CHECK(pulses_1 - before == 150 * PULSES_PER_MM,
          "travelled %d pulses, expected %d", pulses_1 - before, 150 * PULSES_PER_MM);
}

static void test_travel_is_clamped(void)
{
    printf("the firmware clamps the travel, not just the console\n");
    reset_machine();
    home_the_deck();
    move_to_height(5000);
    CHECK(position_pulses == MAX_HEIGHT_MM * PULSES_PER_MM,
          "went to %d pulses, past the top of the travel", (int)position_pulses);
    move_to_height(-200);
    CHECK(position_pulses == MIN_HEIGHT_MM * PULSES_PER_MM,
          "went to %d pulses, below the bottom", (int)position_pulses);
}

static void test_a_move_can_be_stopped(void)
{
    printf("a move in progress stops, and the position stays known\n");
    reset_machine();
    home_the_deck();
    /* Drive the abort from the pulse counter: the old loops could not see a
     * STOP at all, which is the bug this proves is gone. */
    stop_after_pulses = 1000;
    int target_pulses = 700 * PULSES_PER_MM;
    /* Run the move with the stop injected by the fake WritePin below. */
    move_to_height(700);
    stop_after_pulses = 0;
    CHECK(pulses_1 < target_pulses, "the move ran to completion despite a stop");
    CHECK(position_pulses != POSITION_UNKNOWN, "lost the position on a stop");
    CHECK(position_pulses == (MIN_HEIGHT_MM * PULSES_PER_MM) + pulses_1,
          "position %d does not match the %d pulses actually issued",
          (int)position_pulses, pulses_1);
}

static void test_a_limit_switch_stops_a_descent(void)
{
    printf("a limit switch stops a move down and re-establishes the datum\n");
    reset_machine();
    home_the_deck();
    move_to_height(600);
    int before = pulses_1;
    limit_after = down_pulses + 500;   /* the switch closes early on the way down */
    move_to_height(100);
    CHECK(pulses_1 - before < 500 * PULSES_PER_MM, "kept driving past the limit switch");
    CHECK(position_pulses == 0, "the switch is the datum; position was %d",
          (int)position_pulses);
}

static void test_status_frames_go_out(void)
{
    printf("status frames report the height back\n");
    reset_machine();
    home_the_deck();
    tx_count = 0;
    move_to_height(300);
    CHECK(tx_count >= 2, "expected a status frame before and after the move");
    uint8_t *last = tx_frames[tx_count - 1];
    CHECK(last[0] == 0x48 && last[1] == 0x54 && last[2] == OP_STATUS, "not a status frame");
    int32_t mm = (int32_t)((uint32_t)last[4] | ((uint32_t)last[5] << 8)
                         | ((uint32_t)last[6] << 16) | ((uint32_t)last[7] << 24));
    CHECK(mm == 300, "status reported %d mm, expected 300", (int)mm);
    CHECK(last[3] == STATE_IDLE, "status state was %d", last[3]);
}

int main(void)
{
    test_frame_parsing();
    test_resync();
    test_duplicate_sequence_ignored();
    test_stop_is_immediate();
    test_no_move_before_homing();
    test_homing_sets_the_datum();
    test_homing_that_finds_nothing_reports_unknown();
    test_absolute_move_up();
    test_absolute_move_down();
    test_travel_is_clamped();
    test_a_move_can_be_stopped();
    test_a_limit_switch_stops_a_descent();
    test_status_frames_go_out();

    printf("\n%s\n", failures ? "FAILURES ABOVE" : "all firmware logic tests passed");
    return failures ? 1 : 0;
}
