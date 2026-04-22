from django import forms


class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "you@example.com",
                "class": "input",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        max_length=256,
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": "Password",
                "class": "input",
            }
        ),
    )
