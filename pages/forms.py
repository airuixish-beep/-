from django import forms

from .models import FiveElementQuiz, FiveElementSubmission

INPUT_CLASS = "w-full rounded-2xl border border-white/10 bg-xuanor-panel px-4 py-3 text-sm text-xuanor-cream outline-none ring-0 placeholder:text-stone-500 focus:border-xuanor-gold"


class FiveElementQuizForm(forms.Form):
    respondent_name = forms.CharField(max_length=120, required=False, label="称呼")
    respondent_email = forms.EmailField(required=False, label="邮箱")

    def __init__(self, *args, quiz: FiveElementQuiz, **kwargs):
        self.quiz = quiz
        self.questions = list(quiz.questions.filter(is_active=True).prefetch_related("options__scores", "options"))
        super().__init__(*args, **kwargs)
        self._build_fields()
        self._apply_widget_classes()

    def _build_fields(self):
        for question in self.questions:
            choices = [
                (str(option.id), option.label)
                for option in question.options.filter(is_active=True).order_by("sort_order", "id")
            ]
            self.fields[f"question_{question.id}"] = forms.ChoiceField(
                label=question.prompt,
                choices=choices,
                widget=forms.RadioSelect,
                error_messages={"required": "请先完成这一题。"},
            )

    def _apply_widget_classes(self):
        for name, field in self.fields.items():
            if name in {"respondent_name", "respondent_email"}:
                field.widget.attrs["class"] = INPUT_CLASS

    def clean(self):
        cleaned_data = super().clean()
        if not self.questions:
            raise forms.ValidationError("当前测试题目尚未配置完成。")
        return cleaned_data

    def selected_option_ids(self):
        option_ids = []
        for question in self.questions:
            value = self.cleaned_data.get(f"question_{question.id}")
            if value:
                option_ids.append(int(value))
        return option_ids

    def build_submission_payload(self):
        answers = []
        option_map = {
            option.id: option
            for question in self.questions
            for option in question.options.filter(is_active=True)
        }
        for question in self.questions:
            option_id = self.cleaned_data.get(f"question_{question.id}")
            if not option_id:
                continue
            option = option_map.get(int(option_id))
            if option is None:
                continue
            answers.append(
                {
                    "question_id": question.id,
                    "question": question.prompt,
                    "option_id": option.id,
                    "option": option.label,
                }
            )
        return answers


class FiveElementLeadCaptureForm(forms.ModelForm):
    class Meta:
        model = FiveElementSubmission
        fields = ["respondent_name", "respondent_email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["respondent_name"].required = False
        self.fields["respondent_email"].required = False
        self.fields["respondent_name"].widget.attrs["class"] = INPUT_CLASS
        self.fields["respondent_email"].widget.attrs["class"] = INPUT_CLASS
