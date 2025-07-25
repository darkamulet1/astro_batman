import swisseph as swe

print("Swiss Ephemeris version:", swe.version())

# مثال محاسبه لگنا
year, month, day = 1997, 6, 7
hour, minute = 20, 28
lat, lon = 35.6892, 51.3890
tz = 3.5

ut = hour + minute/60 - tz
jd_ut = swe.julday(year, month, day, ut)
swe.set_sid_mode(swe.SIDM_LAHIRI)

houses, ascmc = swe.houses_ex(jd_ut, lat, lon, b'P')
asc = (ascmc[0] - swe.get_ayanamsa_ut(jd_ut)) % 360
print(f"Lagna (Ascendant): {asc:.2f} degrees")
