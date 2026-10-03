from joymedia.patches.register_minimax_h3_workflows import execute as register_workflows


def execute():
	# Production Reference-to-Video renders at 0.98 MP (as Image-to-Video does)
	# instead of 0.4 MP upscaled to the delivery size.
	register_workflows()
