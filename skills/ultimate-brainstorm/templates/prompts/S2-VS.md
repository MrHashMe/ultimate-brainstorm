<!-- ub-template: S2-VS v1 kind=generator -->
Do not load or invoke any skill; this prompt is the whole task.
{{GEN_HEADER}}

STRATEGY {{STRATEGY_ID}} - VERBALIZED SAMPLING LADDER (rule 1 above does not apply to this strategy)
First write 3-5 sentences on how the space of possible answers is shaped. Then run four rounds and keep every response.
Round 1: Generate 5 responses to the brief, each within a separate <response> tag. Each <response> must include a
<text> and a numeric <probability>. Randomly sample the responses from the full distribution.
Round 2: Generate 5 alternative responses to the original brief. Please sample at random from the tails of the
distribution, such that the probability of each response is less than 0.10.
Round 3: Generate 5 more alternative responses, each with probability less than 0.10, whose mechanisms differ from all
earlier responses.
Round 4: Generate 5 alternative responses, each with probability less than 0.01.
Probabilities are rough relative signals, not calibrated likelihoods. Convert all 20 responses into the output format
with the probability in "p".

OUTPUT RULE
Print the shape sentences, then the 20 output-format blocks (at least 10), and nothing else.
{{OUTPUT_RULE}}
