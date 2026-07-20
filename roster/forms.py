from django import forms
from .models import StaffMember


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = ["name", "display_order"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "氏名"}),
            "display_order": forms.NumberInput(attrs={"min": 0}),
        }


class MonthForm(forms.Form):
    year = forms.IntegerField(min_value=2000, max_value=2100, label="年")
    month = forms.IntegerField(min_value=1, max_value=12, label="月")
