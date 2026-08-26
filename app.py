import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import urllib.parse
import os
import io
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
