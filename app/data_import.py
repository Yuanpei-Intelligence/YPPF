import pandas as pd
import os

BASE_DIR = "/Users/rickymac/Documents/20Autmun/ypdev/YPPF/boot/boottest/"


def load():
    # df_2018 = pd.read_csv(BASE_DIR + 'static/2018.csv')
    df_1819 = pd.read_csv("app/append.csv")
    return df_1819
