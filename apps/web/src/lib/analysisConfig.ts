export const BACKGROUND_ANALYSIS_CONFIG = {
  default_window_size_seconds: 60,
  inference: {
    max_annotation_templates: 64,
    max_sample_message_chars: 1200,
    max_samples_per_template: 3,
  },
} satisfies Record<string, unknown>;
